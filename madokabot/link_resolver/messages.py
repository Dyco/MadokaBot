"""Resolver 的 OneBot 消息构造与目标选择。"""

from pathlib import Path

from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)

from ..madoka_bundle.plugins.common import media_delivery
from .config import Config

NICKNAME = get_plugin_config(Config).r_global_nickname.strip()
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".gif"})
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm"})


def build_media_node(
    user_id: int | str,
    task: str | Path | None,
) -> MessageSegment | None:
    """按本地文件后缀构造合并转发节点。"""
    if not task:
        return None

    path = Path(task)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        content = MessageSegment.image(file=path.resolve().as_uri())
    elif suffix in VIDEO_SUFFIXES:
        content = MessageSegment.video(file=path.resolve().as_uri())
    else:
        return None

    return MessageSegment.node_custom(
        user_id=user_id,
        nickname=NICKNAME,
        content=Message(content),
    )


def make_forward_nodes(
    user_id: int | str,
    segments: Message | MessageSegment | list,
) -> MessageSegment | list[MessageSegment]:
    """将消息段包装成 OneBot 合并转发节点。"""

    def make_node(segment: Message | MessageSegment) -> MessageSegment:
        content = segment if isinstance(segment, Message) else Message(segment)
        return MessageSegment.node_custom(
            user_id=user_id,
            nickname=NICKNAME,
            content=content,
        )

    if isinstance(segments, list):
        return [make_node(segment) for segment in segments]
    return make_node(segments)


async def send_forward(
    bot: Bot,
    event: Event,
    segments: MessageSegment | list,
) -> None:
    """向群聊或私聊发送合并转发。"""
    messages = segments if isinstance(segments, list) else [segments]
    if isinstance(event, GroupMessageEvent):
        await bot.send_group_forward_msg(
            group_id=event.group_id,
            messages=messages,
        )
    elif isinstance(event, PrivateMessageEvent):
        await bot.send_private_forward_msg(
            user_id=event.user_id,
            messages=messages,
        )


async def upload_file(
    bot: Bot,
    event: Event,
    file_path: str | Path,
    name: str,
) -> None:
    """通过通用媒体服务向事件目标上传文件。"""
    media = media_delivery.inspect(file_path, name)
    await media_delivery.upload_file(bot, event, media)


def get_target_id(event: Event) -> int | None:
    if isinstance(event, GroupMessageEvent):
        return event.group_id
    if isinstance(event, PrivateMessageEvent):
        return event.user_id
    return None
