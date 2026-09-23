import functools
import math
import re
from contextlib import suppress
from typing import Any, Dict, Generator, List, Mapping, Optional

from aiohttp import ClientSession
from cachetools import TTLCache
from cachetools.keys import hashkey
from nonebot import get_bot as nonebot_get_bot
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

from madokabot.core.config import config as madoka_config
from .config import config

bot_offline = False


def get_proxy(open_proxy: bool = True) -> Optional[str]:
    """Return the shared HTTP proxy, with the legacy RSS setting as fallback."""
    if not open_proxy:
        return None

    proxy = madoka_config.proxy or config.rss_proxy
    if not proxy:
        return None
    proxy_url = str(proxy).strip()
    return proxy_url if "://" in proxy_url else f"http://{proxy_url}"


def get_summary(item: Dict[str, Any]) -> str:
    """Extract an entry's HTML summary across common feedparser shapes."""
    content = item.get("content")
    summary = (
        str(content[0].get("value", ""))
        if isinstance(content, list) and content
        else str(item.get("summary", item.get("description", "")))
    )
    return f"<div>{summary}</div>" if re.search(r"^https?://", summary) else summary


def get_author(item: Dict[str, Any]) -> str:
    return str(item.get("author", ""))


def get_http_caching_headers(
    headers: Optional[Mapping[str, Any]],
) -> Dict[str, Optional[str]]:
    return (
        {
            "Last-Modified": headers.get("Last-Modified") or headers.get("Date"),
            "ETag": headers.get("ETag"),
        }
        if headers
        else {"Last-Modified": None, "ETag": None}
    )


def convert_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
    i = min(int(math.floor(math.log(size_bytes, 1024))), len(size_name) - 1)
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def cached_async(cache, key=hashkey):  # type: ignore
    """
    https://github.com/tkem/cachetools/commit/3f073633ed4f36f05b57838a3e5655e14d3e3524
    """

    def decorator(func):  # type: ignore
        if cache is None:

            async def wrapper(*args, **kwargs):  # type: ignore
                return await func(*args, **kwargs)

        else:

            async def wrapper(*args, **kwargs):  # type: ignore
                k = key(*args, **kwargs)
                with suppress(KeyError):  # key not found
                    return cache[k]
                v = await func(*args, **kwargs)
                with suppress(ValueError):  # value too large
                    cache[k] = v
                return v

        return functools.update_wrapper(wrapper, func)

    return decorator


@cached_async(TTLCache(maxsize=1, ttl=300))  # type: ignore
async def get_bot_friend_list(bot: Bot) -> List[int]:
    friend_list = await bot.get_friend_list()
    return [i["user_id"] for i in friend_list]


@cached_async(TTLCache(maxsize=1, ttl=300))  # type: ignore
async def get_bot_group_list(bot: Bot) -> List[int]:
    group_list = await bot.get_group_list()
    return [i["group_id"] for i in group_list]


@cached_async(TTLCache(maxsize=1, ttl=300))  # type: ignore
async def get_bot_guild_channel_list(
    bot: Bot, guild_id: Optional[str] = None
) -> List[str]:
    guild_list = await bot.get_guild_list()
    if guild_id is None:
        return [i["guild_id"] for i in guild_list]
    elif guild_id in [i["guild_id"] for i in guild_list]:
        channel_list = await bot.get_guild_channel_list(guild_id=guild_id)
        return [i["channel_id"] for i in channel_list]
    return []


async def send_msg(
    msg: str,
    user_ids: Optional[List[str]] = None,
    group_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    msg: str
    user: List[str]
    group: List[str]

    发送消息到私聊或群聊
    """
    bot: Bot = await get_bot()  # type: ignore
    if bot is None:
        raise ValueError("There are not bots to get.")
    msg_id = []
    if group_ids:
        for group_id in group_ids:
            msg_id.append(await bot.send_group_msg(group_id=int(group_id), message=msg))
    if user_ids:
        for user_id in user_ids:
            msg_id.append(await bot.send_private_msg(user_id=int(user_id), message=msg))
    return msg_id


# 校验正则表达式合法性
def regex_validate(regex: str) -> bool:
    try:
        re.compile(regex)
        return True
    except re.error:
        return False


# 过滤合法好友
async def filter_valid_user_id_list(bot: Bot, user_id_list: List[str]) -> List[str]:
    friend_list = await get_bot_friend_list(bot)
    valid_user_id_list = [
        user_id
        for user_id in user_id_list
        if user_id.isdigit() and int(user_id) in friend_list
    ]
    if invalid_user_id_list := [
        user_id for user_id in user_id_list if user_id not in valid_user_id_list
    ]:
        logger.warning(
            f"QQ号[{','.join(invalid_user_id_list)}]不是Bot[{bot.self_id}]的好友"
        )
    return valid_user_id_list


# 过滤合法群组
async def filter_valid_group_id_list(bot: Bot, group_id_list: List[str]) -> List[str]:
    group_list = await get_bot_group_list(bot)
    valid_group_id_list = [
        group_id
        for group_id in group_id_list
        if group_id.isdigit() and int(group_id) in group_list
    ]
    if invalid_group_id_list := [
        group_id for group_id in group_id_list if group_id not in valid_group_id_list
    ]:
        logger.warning(
            f"Bot[{bot.self_id}]未加入群组[{','.join(invalid_group_id_list)}]"
        )
    return valid_group_id_list


# 过滤合法频道
async def filter_valid_guild_channel_id_list(
    bot: Bot, guild_channel_id_list: List[str]
) -> List[str]:
    valid_guild_channel_id_list = []
    for guild_channel_id in guild_channel_id_list:
        try:
            guild_id, channel_id = guild_channel_id.split("@", 1)
        except ValueError:
            logger.warning(f"频道订阅标识格式错误：{guild_channel_id}")
            continue
        guild_list = await get_bot_guild_channel_list(bot)
        if guild_id not in guild_list:
            guild_name = (await bot.get_guild_meta_by_guest(guild_id=guild_id))[
                "guild_name"
            ]
            logger.warning(f"Bot[{bot.self_id}]未加入频道 {guild_name}[{guild_id}]")
            continue

        channel_list = await get_bot_guild_channel_list(bot, guild_id=guild_id)
        if channel_id not in channel_list:
            guild_name = (await bot.get_guild_meta_by_guest(guild_id=guild_id))[
                "guild_name"
            ]
            logger.warning(
                f"Bot[{bot.self_id}]未加入频道 {guild_name}[{guild_id}]的子频道[{channel_id}]"
            )
            continue
        valid_guild_channel_id_list.append(guild_channel_id)
    return valid_guild_channel_id_list


def partition_list(
    input_list: List[Any], partition_size: int
) -> Generator[List[Any], None, None]:
    for i in range(0, len(input_list), partition_size):
        yield input_list[i : i + partition_size]


async def send_message_to_telegram_admin(message: str) -> None:
    if not config.telegram_admin_ids or not config.telegram_bot_token:
        return
    try:
        async with ClientSession(raise_for_status=True) as session:
            await session.post(
                f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": config.telegram_admin_ids[0],
                    "text": message,
                },
                proxy=get_proxy(),
            )
    except Exception as e:
        logger.error(f"发送到 Telegram 失败:\n {e}")


async def get_bot() -> Optional[Bot]:
    global bot_offline
    bot: Optional[Bot] = None
    try:
        bot = nonebot_get_bot()  # type: ignore
        bot_offline = False
    except ValueError:
        if not bot_offline and config.telegram_admin_ids and config.telegram_bot_token:
            await send_message_to_telegram_admin("QQ Bot 已离线！")
            logger.warning("Bot 已离线！")
            bot_offline = True
    return bot
