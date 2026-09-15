import asyncio
from typing import Any, Dict, Optional, Tuple

import aiohttp
import feedparser
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger
from tinydb import TinyDB
from yarl import URL

from . import handlers as _handlers  # noqa: F401  # 注册默认及站点处理器
from ..madoka_bundle.plugins.common import is_group_whitelisted
from ..madoka_bundle.plugins.greeting import send_message_to_admin
from .cache import cache_filter, dict_hash
from .config import DATA_PATH, config
from .parser import FeedProcessor
from .routes.danbooru import fetch_danbooru, is_danbooru_url
from .subscription import Rss
from .utils import (
    filter_valid_group_id_list,
    filter_valid_guild_channel_id_list,
    filter_valid_user_id_list,
    get_bot,
    get_http_caching_headers,
    get_proxy,
)

HEADERS = {
    "Accept": "application/xhtml+xml,application/xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "max-age=0",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/111.0.0.0 Safari/537.36"
    ),
    "Connection": "keep-alive",
    "Content-Type": "application/xml; charset=utf-8",
}


def _request_mode(proxy: Optional[str]) -> str:
    return "代理" if proxy else "直连"


def _log_http_error(
    rss_url: str,
    proxy: Optional[str],
    exc: aiohttp.ClientResponseError,
) -> None:
    headers = exc.headers or {}
    logger.error(
        f"[{rss_url}] {_request_mode(proxy)}请求失败：HTTP {exc.status} "
        f"{exc.message or 'Unknown Error'}；"
        f"Content-Type={headers.get('Content-Type') or '未知'}；"
        f"Cf-Mitigated={headers.get('Cf-Mitigated') or '无'}"
    )


def _log_invalid_feed(
    rss_url: str,
    proxy: Optional[str],
    response: aiohttp.ClientResponse,
    body: str,
    parsed: Dict[str, Any],
) -> None:
    bozo_exception = parsed.get("bozo_exception")
    logger.error(
        f"[{rss_url}] {_request_mode(proxy)}请求未解析出 RSS/Atom："
        f"HTTP {response.status}；"
        f"Content-Type={response.headers.get('Content-Type') or '未知'}；"
        f"Cf-Mitigated={response.headers.get('Cf-Mitigated') or '无'}；"
        f"响应长度={len(body)}；"
        f"解析错误={bozo_exception or '无'}"
    )


async def filter_and_validate_rss(rss: Rss, bot: Bot) -> Rss:
    original_targets = (rss.user_id[:], rss.group_id[:], rss.guild_channel_id[:])
    if rss.user_id:
        rss.user_id = await filter_valid_user_id_list(bot, rss.user_id)
    if rss.group_id:
        rss.group_id = await filter_valid_group_id_list(bot, rss.group_id)
    if rss.guild_channel_id:
        rss.guild_channel_id = await filter_valid_guild_channel_id_list(
            bot, rss.guild_channel_id
        )
    if original_targets != (rss.user_id, rss.group_id, rss.guild_channel_id):
        rss.upsert()
    return rss


async def save_first_time_fetch(rss: Rss, new_rss: Dict[str, Any]) -> None:
    _file = DATA_PATH / f"{Rss.handle_name(rss.name)}.json"
    result = [cache_filter(entry) for entry in new_rss["entries"]]
    for r in result:
        r["hash"] = dict_hash(r)

    with TinyDB(
        _file,
        encoding="utf-8",
        sort_keys=True,
        indent=4,
        ensure_ascii=False,
    ) as db:
        db.insert_multiple(result)

    logger.info(f"{rss.name} 第一次抓取成功！")


# 抓取 feed，读取缓存，检查更新，对更新进行处理
async def start(rss: Rss) -> None:
    bot: Bot = await get_bot()  # type: ignore
    if bot is None:
        return

    if rss.group_id and not any(
        is_group_whitelisted(group_id) for group_id in rss.group_id
    ):
        logger.info(f"{rss.name} 没有 RSS 白名单群组，跳过本次更新")
        return

    # 先检查订阅者是否合法
    rss = await filter_and_validate_rss(rss, bot)
    if not any([rss.user_id, rss.group_id, rss.guild_channel_id]):
        await auto_stop_and_notify_admin(rss, bot)
        return

    new_rss, cached = await fetch_rss(rss)
    # 检查是否存在rss记录
    _file = DATA_PATH / f"{Rss.handle_name(rss.name)}.json"
    first_time_fetch = not _file.exists()

    if cached:
        logger.info(f"{rss.name} 没有新信息")
        return

    if not new_rss or not new_rss.get("feed"):
        rss.error_count += 1
        logger.warning(f"{rss.name} 抓取失败！")

        if first_time_fetch:
            if get_proxy() and not rss.img_proxy:
                rss.img_proxy = True
                logger.info(f"{rss.name} 第一次抓取失败，自动使用代理抓取")
                await start(rss)
            else:
                await auto_stop_and_notify_admin(rss, bot)

        if rss.error_count >= 100:
            await auto_stop_and_notify_admin(rss, bot)
        return

    if new_rss.get("feed") and rss.error_count > 0:
        rss.error_count = 0

    if first_time_fetch:
        await save_first_time_fetch(rss, new_rss)
        return

    processor = FeedProcessor(rss=rss)
    await processor.start(rss_name=rss.name, new_rss=new_rss)


async def auto_stop_and_notify_admin(rss: Rss, bot: Bot) -> None:
    from .scheduler import delete_job

    rss.stop = True
    rss.upsert()
    delete_job(rss)
    cookies_str = "及 cookies " if rss.cookies else ""
    if not any([rss.user_id, rss.group_id, rss.guild_channel_id]):
        msg = f"{rss.name}[{rss.get_url()}]无人订阅！已自动停止更新！"
    elif rss.error_count >= 100:
        msg = f"{rss.name}[{rss.get_url()}]已经连续抓取失败超过 100 次！已自动停止更新！请检查订阅地址{cookies_str}！"
    else:
        msg = f"{rss.name}[{rss.get_url()}]第一次抓取失败！已自动停止更新！请检查订阅地址{cookies_str}！"
    await send_message_to_admin(msg, bot)


async def fetch_rss_backup(
    rss: Rss, session: aiohttp.ClientSession, proxy: Optional[str]
) -> Dict[str, Any]:
    d = {}
    for rsshub_url in config.rsshub_backup:
        rss_url = rss.get_url(rsshub=str(rsshub_url))
        try:
            resp = await session.get(rss_url, proxy=proxy)
            body = await resp.text()
            d = feedparser.parse(body)
            if not d.get("feed"):
                _log_invalid_feed(rss_url, proxy, resp, body, d)
            if d.get("feed"):
                logger.info(f"[{rss_url}]抓取成功！")
                break
        except asyncio.TimeoutError:
            logger.error(
                f"[{rss_url}] {_request_mode(proxy)}请求超时！"
                "将使用下一个备用 RSSHub 地址"
            )
        except aiohttp.ClientResponseError as exc:
            _log_http_error(rss_url, proxy, exc)
        except Exception as exc:
            logger.exception(
                f"[{rss_url}] {_request_mode(proxy)}请求异常："
                f"{type(exc).__name__}: {exc}；将使用下一个备用 RSSHub 地址"
            )
            continue
    return d


# 获取 RSS 并解析为 json
async def fetch_rss(rss: Rss) -> Tuple[Dict[str, Any], bool]:
    rss_url = rss.get_url()
    # 对本机部署的 RSSHub 不使用代理
    local_host = ["localhost", "127.0.0.1"]
    proxy = get_proxy(rss.img_proxy) if URL(rss_url).host not in local_host else None

    if is_danbooru_url(rss_url):
        try:
            data, cached, response_headers = await fetch_danbooru(rss, proxy)
            if not config.debug:
                rss.etag = response_headers.get("ETag") or rss.etag
                rss.last_modified = (
                    response_headers.get("Last-Modified") or rss.last_modified
                )
                rss.upsert()
            return data, cached
        except asyncio.TimeoutError:
            logger.error(
                f"[{rss_url}] Danbooru API {_request_mode(proxy)}请求超时（10 秒）"
            )
        except aiohttp.ClientResponseError as exc:
            _log_http_error(rss_url, proxy, exc)
        except Exception as exc:
            logger.exception(
                f"[{rss_url}] Danbooru API {_request_mode(proxy)}请求异常："
                f"{type(exc).__name__}: {exc}"
            )
        return {}, False

    cookies = rss.cookies or None
    headers = HEADERS.copy()
    if cookies:
        headers["cookie"] = cookies
    d = {}
    cached = False

    if not config.rsshub_backup and not config.debug:
        if rss.etag:
            headers["If-None-Match"] = rss.etag
        if rss.last_modified:
            headers["If-Modified-Since"] = rss.last_modified

    async with aiohttp.ClientSession(
        headers=headers,
        raise_for_status=True,
        timeout=aiohttp.ClientTimeout(10),
    ) as session:
        try:
            resp = await session.get(rss_url, proxy=proxy)
            if not config.rsshub_backup:
                http_caching_headers = get_http_caching_headers(resp.headers)
                rss.etag = http_caching_headers["ETag"]
                rss.last_modified = http_caching_headers["Last-Modified"]
                rss.upsert()
            content_length = resp.headers.get("Content-Length")
            if (resp.status == 200 and content_length == "0") or resp.status == 304:
                cached = True
            body = await resp.text()
            d = feedparser.parse(body)
            if not cached and not d.get("feed"):
                _log_invalid_feed(rss_url, proxy, resp, body, d)
        except asyncio.TimeoutError:
            logger.error(
                f"[{rss_url}] {_request_mode(proxy)}请求超时（10 秒）"
            )
            if not URL(rss.url).scheme and config.rsshub_backup:
                d = await fetch_rss_backup(rss, session, proxy)
        except aiohttp.ClientResponseError as exc:
            _log_http_error(rss_url, proxy, exc)
            if not URL(rss.url).scheme and config.rsshub_backup:
                d = await fetch_rss_backup(rss, session, proxy)
        except Exception as exc:
            if not URL(rss.url).scheme and config.rsshub_backup:
                logger.exception(
                    f"[{rss_url}] {_request_mode(proxy)}请求异常："
                    f"{type(exc).__name__}: {exc}；将使用备用 RSSHub 地址"
                )
                d = await fetch_rss_backup(rss, session, proxy)
            else:
                logger.exception(
                    f"[{rss_url}] {_request_mode(proxy)}请求异常："
                    f"{type(exc).__name__}: {exc}"
                )
    return d, cached
