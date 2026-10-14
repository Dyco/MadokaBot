"""微博图文与视频分享解析。"""

import re
from html import unescape
from pathlib import Path

import aiohttp
import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..delivery import media_delivery, send_resolved_video
from ..downloads import download_image, download_video
from ..matchers import WEIBO_PATTERN
from ..matchers import weibo_matcher as weibo
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.weibo import (
    WEIBO_HEADERS,
    create_weibo_client,
    get_weibo_images,
    get_weibo_post,
    get_weibo_video_url,
)
from ..state import is_content_enabled
from .runtime import GLOBAL_NICKNAME, WEIBO_PROXY
from .video import _find_video_duration_seconds, _skip_video_for_duration


@weibo.handle()
@resolve_handler
@resolve_controller
async def wb(bot: Bot, event: GroupMessageEvent) -> None:
    """使用统一 Cookie 读取网页或卡片分享，按群开关发送图文及视频。"""
    message = get_resolver_message(event).replace("&amp;", "&")
    url_match = re.search(WEIBO_PATTERN, message, re.IGNORECASE)
    if not url_match:
        return
    try:
        async with create_weibo_client(WEIBO_PROXY) as client:
            post = await get_weibo_post(client, url_match[0])
    except FileNotFoundError:
        logger.warning("[微博] 未找到 Cookie 资源：assets/cookies/weibo_cookies.txt")
        return
    except ValueError as exc:
        logger.warning(f"[微博] 作品获取失败：{exc}")
        return
    except (OSError, httpx.HTTPError) as exc:
        logger.warning(f"[微博] 作品请求失败：{type(exc).__name__}")
        return

    target_id = get_target_id(event)
    text = post.get("text_raw") or unescape(
        re.sub(r"<[^>]+>", "", post.get("text") or "")
    )
    source = unescape(re.sub(r"<[^>]+>", "", post.get("source") or ""))
    info = MessageSegment.text(
        f"{GLOBAL_NICKNAME}识别：微博\n"
        f"作者：{post.get('user', {}).get('screen_name', '未知')}\n"
        f"{text}\n{source}\t{post.get('region_name', '')}"
    )
    nodes = list(make_forward_nodes(bot.self_id, [info]))
    paths = []
    try:
        if is_content_enabled(target_id, "weibo", "image"):
            async with aiohttp.ClientSession(trust_env=False) as session:
                for url in get_weibo_images(post):
                    try:
                        path = await download_image(
                            url,
                            proxy=WEIBO_PROXY,
                            session=session,
                            headers=WEIBO_HEADERS,
                        )
                    except (aiohttp.ClientError, OSError) as exc:
                        logger.warning(
                            f"[微博] 图片下载失败，跳过当前图片：{type(exc).__name__}"
                        )
                        continue
                    paths.append(path)
                    nodes.append(
                        make_forward_nodes(
                            bot.self_id,
                            MessageSegment.image(Path(path).resolve().as_uri()),
                        )
                    )
        await send_forward(bot, event, nodes)
    finally:
        for path in paths:
            Path(path).unlink(missing_ok=True)

    if not is_content_enabled(target_id, "weibo", "video"):
        return
    video_url = get_weibo_video_url(post)
    if not video_url or _skip_video_for_duration(
        "微博", _find_video_duration_seconds(post.get("page_info"))
    ):
        return
    try:
        path = await download_video(
            video_url,
            WEIBO_PROXY,
            ext_headers=WEIBO_HEADERS,
            max_size=media_delivery.video_compress_limit,
        )
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"[微博] 视频超过大小限制，已跳过下载和发送：{exc}")
        return
    except ValueError as exc:
        await weibo.finish(f"视频无法下载：{exc}")
    await send_resolved_video(event, path, WEIBO_PROXY)
