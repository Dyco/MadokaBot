import asyncio
import re
from collections import defaultdict
from contextlib import suppress
from typing import Any, Callable, Coroutine, DefaultDict, Dict, List, Tuple, Union

import arrow
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import NetworkError
from nonebot.log import logger

from ..madoka_bundle.plugins.common import is_group_whitelisted
from .cache import insert_into_cache_db, write_item
from .config import config
from .subscription import Rss
from .utils import get_bot

sending_lock: DefaultDict[Tuple[Union[int, str], str], asyncio.Lock] = defaultdict(
    asyncio.Lock
)


# 发送消息
async def send_msg(
    rss: Rss, messages: List[str], items: List[Dict[str, Any]], header_message: str
) -> bool:
    bot: Bot = await get_bot()  # type: ignore
    if bot is None:
        return False
    if not messages:
        return False
    flag = False
    group_ids: List[str] = []
    if rss.user_id:
        flag = any(
            await asyncio.gather(
                *[
                    send_private_msg(
                        bot,
                        messages,
                        int(user_id),
                        items,
                        header_message,
                        config.rss_auto_forward or rss.send_forward_msg,
                    )
                    for user_id in rss.user_id
                ]
            )
        )
    if rss.group_id:
        group_ids = [
            str(group_id)
            for group_id in rss.group_id
            if str(group_id).isdigit() and is_group_whitelisted(group_id)
        ]
        if not group_ids:
            logger.info(f"{rss.name} 没有可用的 RSS 白名单群组，跳过群消息推送")
        flag = (
            any(
                await asyncio.gather(
                    *[
                        send_group_msg(
                            bot,
                            messages,
                            int(group_id),
                            items,
                            header_message,
                            config.rss_auto_forward or rss.send_forward_msg,
                        )
                        for group_id in group_ids
                    ]
                )
            )
            or flag
        )
        if not group_ids and not rss.user_id and not rss.guild_channel_id:
            return True
    if rss.guild_channel_id:
        flag = (
            any(
                await asyncio.gather(
                    *[
                        send_guild_channel_msg(
                            bot, messages, guild_channel_id, items, header_message
                        )
                        for guild_channel_id in rss.guild_channel_id
                    ]
                )
            )
            or flag
        )
    return flag


# 发送私聊消息
async def send_private_msg(
    bot: Bot,
    message: List[str],
    user_id: int,
    items: List[Dict[str, Any]],
    header_message: str,
    send_forward_msg: bool,
) -> bool:
    return await send_msgs_with_lock(
        bot=bot,
        messages=message,
        target_id=user_id,
        target_type="private",
        items=items,
        header_message=header_message,
        send_func=lambda user_id, message: bot.send_private_msg(
            user_id=user_id, message=message  # type: ignore
        ),
        send_forward_msg=send_forward_msg,
    )


# 发送群聊消息
async def send_group_msg(
    bot: Bot,
    message: List[str],
    group_id: int,
    items: List[Dict[str, Any]],
    header_message: str,
    send_forward_msg: bool,
) -> bool:
    return await send_msgs_with_lock(
        bot=bot,
        messages=message,
        target_id=group_id,
        target_type="group",
        items=items,
        header_message=header_message,
        send_func=lambda group_id, message: bot.send_group_msg(
            group_id=group_id, message=message  # type: ignore
        ),
        send_forward_msg=send_forward_msg,
    )


# 发送频道消息
async def send_guild_channel_msg(
    bot: Bot,
    message: List[str],
    guild_channel_id: str,
    items: List[Dict[str, Any]],
    header_message: str,
) -> bool:
    guild_id, channel_id = guild_channel_id.split("@")
    return await send_msgs_with_lock(
        bot=bot,
        messages=message,
        target_id=guild_channel_id,
        target_type="guild_channel",
        items=items,
        header_message=header_message,
        send_func=lambda guild_channel_id, message: bot.send_guild_channel_msg(
            message=message, guild_id=guild_id, channel_id=channel_id
        ),
    )


async def send_single_msg(
    message: str,
    target_id: Union[int, str],
    item: Dict[str, Any],
    header_message: str,
    send_func: Callable[[Union[int, str], str], Coroutine[Any, Any, Dict[str, Any]]],
) -> bool:
    flag = False
    try:
        formatted_message = (
            f"{header_message}\n----------------------\n{message}"
            if header_message
            else message
        )
        await send_func(target_id, formatted_message)
        flag = True
    except Exception as e:
        error_msg = f"E: {repr(e)}\n消息发送失败！\n链接：[{item.get('link')}]"
        logger.error(error_msg)
        if item.get("to_send"):
            flag = True
            with suppress(Exception):
                await send_func(target_id, error_msg)
    return flag


async def send_multiple_msgs(
    messages: List[str],
    target_id: Union[int, str],
    items: List[Dict[str, Any]],
    header_message: str,
    send_func: Callable[[Union[int, str], str], Coroutine[Any, Any, Dict[str, Any]]],
) -> bool:
    flag = False
    for message, item in zip(messages, items):
        flag = (
            await send_single_msg(message, target_id, item, header_message, send_func)
            or flag
        )
    return flag


async def send_msgs_with_lock(
    bot: Bot,
    messages: List[str],
    target_id: Union[int, str],
    target_type: str,
    items: List[Dict[str, Any]],
    header_message: str,
    send_func: Callable[[Union[int, str], str], Coroutine[Any, Any, Dict[str, Any]]],
    send_forward_msg: bool = False,
) -> bool:
    start_time = arrow.now()
    async with sending_lock[(target_id, target_type)]:
        if _is_imageboard_batch(items):
            imageboard_entries = _imageboard_entries(messages, items)
            if not imageboard_entries:
                flag = True
            elif send_forward_msg and target_type != "guild_channel":
                flag = await try_sending_forward_msg(
                    bot,
                    messages,
                    target_id,
                    target_type,
                    items,
                    header_message,
                    send_func,
                )
            else:
                contents = [header_message] + [
                    message for message, _ in imageboard_entries
                ]
                content_items = [imageboard_entries[0][1]] + [
                    item for _, item in imageboard_entries
                ]
                flag = await send_multiple_msgs(
                    contents, target_id, content_items, "", send_func
                )
        elif send_forward_msg and target_type != "guild_channel":
            flag = await try_sending_forward_msg(
                bot, messages, target_id, target_type, items, header_message, send_func
            )
        elif len(messages) == 1:
            flag = await send_single_msg(
                messages[0], target_id, items[0], header_message, send_func
            )
        else:
            flag = await send_multiple_msgs(
                messages, target_id, items, header_message, send_func
            )
        await asyncio.sleep(max(1 - (arrow.now() - start_time).total_seconds(), 0))
    return flag


async def try_sending_forward_msg(
    bot: Bot,
    messages: List[str],
    target_id: Union[int, str],
    target_type: str,
    items: List[Dict[str, Any]],
    header_message: str,
    send_func: Callable[[Union[int, str], str], Coroutine[Any, Any, Dict[str, Any]]],
) -> bool:
    contents = _forward_message_contents(header_message, messages, items)
    if not contents:
        return True
    forward_messages = handle_forward_message(bot, contents)
    try:
        if target_type == "private":
            await bot.send_private_forward_msg(
                user_id=target_id, messages=forward_messages
            )
        elif target_type == "group":
            await bot.send_group_forward_msg(
                group_id=target_id, messages=forward_messages
            )
        flag = True
    except NetworkError:
        # 如果图片体积过大或数量过多，很可能触发这个错误，但实际上发送成功，不过高概率吞图，只警告不处理
        logger.warning("图片过大或数量过多，可能发送失败！")
        flag = True
    except Exception as e:
        logger.warning(f"E: {repr(e)}\n合并消息发送失败！将尝试逐条发送！")
        if _is_imageboard_batch(items):
            imageboard_entries = _imageboard_entries(messages, items)
            fallback_contents = [header_message] + [
                message for message, _ in imageboard_entries
            ]
            fallback_items = [imageboard_entries[0][1]] + [
                item for _, item in imageboard_entries
            ]
            flag = await send_multiple_msgs(
                fallback_contents, target_id, fallback_items, "", send_func
            )
        else:
            flag = await send_multiple_msgs(
                messages, target_id, items, header_message, send_func
            )
    return flag


def handle_forward_message(bot: Bot, messages: List[str]) -> Message:
    nicknames = list(getattr(config, "nickname", set()))
    return Message(
        [
            MessageSegment.node_custom(
                user_id=int(bot.self_id),
                nickname=nicknames[0] if nicknames else "\u200b",
                content=message,
            )
            for message in messages
        ]
    )


def _is_imageboard_item(item: Dict[str, Any]) -> bool:
    if "danbooru_media_url" in item or "imageboard_character" in item:
        return True
    return bool(
        re.search(
            r"https?://(?:www\.)?(?:yande\.re|danbooru\.donmai\.us)/",
            str(item.get("link") or ""),
            flags=re.IGNORECASE,
        )
    )


def _is_imageboard_batch(items: List[Dict[str, Any]]) -> bool:
    return any(_is_imageboard_item(item) for item in items)


def _metadata_value(item: Dict[str, Any], message: str, label: str) -> str:
    value = item.get(
        "imageboard_character" if label == "角色" else "imageboard_copyright"
    )
    if not value:
        danbooru_key = (
            "danbooru_character" if label == "角色" else "danbooru_copyright"
        )
        value = item.get(danbooru_key)
    if value:
        return str(value).strip()
    match = re.search(rf"(?m)^{re.escape(label)}[：:]\s*(.+?)\s*$", message)
    return match.group(1).strip() if match else ""


def _imageboard_detail(item: Dict[str, Any], message: str) -> str:
    character = _metadata_value(item, message, "角色")
    copyright = _metadata_value(item, message, "作品")
    if not character and not copyright:
        return ""

    lines = []
    if character:
        lines.append(f"角色：{character}")
    if copyright:
        lines.append(f"作品：{copyright}")

    post_url = str(item.get("link") or item.get("guid") or "").strip()
    if post_url:
        lines.append(f"链接：{post_url}")

    images = re.findall(r"\[CQ:image,[^\]]+\]", message, flags=re.IGNORECASE)
    lines.extend(images)
    if not images:
        image_errors = [
            line.strip()
            for line in message.splitlines()
            if "图片走丢啦" in line or "视频预览" in line
        ]
        lines.extend(image_errors)
    return "\n".join(lines)


def _imageboard_entries(
    messages: List[str], items: List[Dict[str, Any]]
) -> List[Tuple[str, Dict[str, Any]]]:
    entries = []
    for message, item in zip(messages, items):
        if detail := _imageboard_detail(item, message):
            entries.append((detail, item))
    return entries


def _forward_message_contents(
    header_message: str, messages: List[str], items: List[Dict[str, Any]]
) -> List[str]:
    """图片站每条帖子合成一个详情节点，普通更新仍拆分链接和正文。"""
    if _is_imageboard_batch(items):
        imageboard_entries = _imageboard_entries(messages, items)
        if not imageboard_entries:
            return []
        return [header_message] + [message for message, _ in imageboard_entries]

    contents = [header_message]
    link_pattern = re.compile(r"(?m)^链接：([^\r\n]+)\r?\n?")
    for message in messages:
        links = link_pattern.findall(message)
        details = link_pattern.sub("", message).strip()
        if links:
            contents.append("链接地址：\n" + "\n".join(links))
        if details:
            contents.append(details)
    return contents


# 发送消息并写入文件
async def handle_send_msgs(
    rss: Rss, messages: List[str], items: List[Dict[str, Any]], state: Dict[str, Any]
) -> None:
    db = state["tinydb"]
    header_message = state["header_message"]

    if await send_msg(rss, messages, items, header_message):
        if rss.duplicate_filter_mode:
            for item in items:
                insert_into_cache_db(
                    conn=state["conn"], item=item, image_hash=item["image_hash"]
                )

        for item in items:
            if item.get("to_send"):
                item.pop("to_send")

    else:
        for item in items:
            item["to_send"] = True

        state["error_count"] += len(messages)

    for item in items:
        write_item(db, item)
