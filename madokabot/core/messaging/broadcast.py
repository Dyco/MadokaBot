"""群消息批量发送支持。"""

import asyncio
import random
from collections.abc import Iterable

from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageSegment,
    OneBotV11AdapterException,
)
from nonebot.compat import type_validate_python

_broadcast_lock = asyncio.Lock()


def _prepare_message(message: Message) -> Message:
    """移除原会话引用，并使用可跨群发送的媒体地址。"""
    prepared = message.copy().exclude("reply")
    for segment in prepared:
        if segment.type in {"image", "record", "video"} and segment.data.get("url"):
            segment.data["file"] = segment.data["url"]
    return prepared


async def _prepare_forward_nodes(bot: Bot, forward_id: str) -> list[MessageSegment]:
    """读取并反序列化合并转发节点，保留发送者和嵌套合并内容。"""
    forward = await bot.get_forward_msg(id=forward_id)
    nodes = []
    for item in forward["messages"]:
        sender = item["sender"]
        content = _prepare_message(type_validate_python(Message, item["content"]))
        for index, segment in enumerate(content):
            if segment.type == "forward":
                content[index] = MessageSegment.node_custom(
                    user_id=int(sender["user_id"]),
                    nickname=sender["nickname"],
                    content=Message(
                        await _prepare_forward_nodes(bot, segment.data["id"])
                    ),
                )
        nodes.append(
            MessageSegment.node_custom(
                user_id=int(sender["user_id"]),
                nickname=sender["nickname"],
                content=content,
            )
        )
    return nodes


async def broadcast_message(
    bot: Bot,
    group_ids: Iterable[str | int],
    message: Message,
    *,
    delay: tuple[float, float] = (1.0, 3.0),
) -> tuple[int, list[str]]:
    """依次向各群发送消息，随机错开发送并返回成功数和失败群号。"""
    groups = list(dict.fromkeys(str(group_id) for group_id in group_ids))
    if not groups:
        return 0, []
    prepared = _prepare_message(message)
    if not prepared:
        raise ValueError("消息内容为空")

    nodes = None
    if len(prepared) == 1 and prepared[0].type == "forward":
        nodes = await _prepare_forward_nodes(bot, prepared[0].data["id"])
        if not nodes:
            raise ValueError("合并消息内容为空")

    sent = 0
    failed = []
    async with _broadcast_lock:
        for group_id in groups:
            await asyncio.sleep(random.uniform(*delay))
            try:
                if nodes is not None:
                    await bot.send_group_forward_msg(
                        group_id=int(group_id), messages=nodes
                    )
                else:
                    await bot.send_group_msg(group_id=int(group_id), message=prepared)
            except OneBotV11AdapterException:
                logger.exception(f"群发消息失败：机器人 {bot.self_id}，群 {group_id}")
                failed.append(group_id)
            else:
                sent += 1
    return sent, failed
