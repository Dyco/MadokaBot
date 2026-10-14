"""tiktok 链接解析事件处理器。"""

import re

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    CACHE_DIR,
)
from ..matchers import (
    TIKTOK_PATTERN,
)
from ..matchers import (
    tiktok_matcher as tik,
)
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.youtube import download_ytb_video, get_video_info
from ..state import is_content_enabled
from .runtime import (
    GLOBAL_NICKNAME,
    TIKTOK_PROXY,
)
from .video import (
    _skip_video_for_duration,
)


@tik.handle()
@resolve_handler
@resolve_controller
async def tiktok(bot: Bot, event: GroupMessageEvent) -> None:
    """使用 Netscape Cookie 解析 TikTok，视频关闭时跳过文件下载。"""
    url_match = re.search(
        TIKTOK_PATTERN,
        get_resolver_message(event).replace("&amp;", "&"),
        re.IGNORECASE,
    )
    if not url_match:
        return
    url = url_match[0]
    try:
        video_info = await get_video_info(url, TIKTOK_PROXY, "tiktok")
    except RuntimeError as exc:
        await tik.finish(str(exc))

    await send_forward(
        bot,
        event,
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(
                f"{GLOBAL_NICKNAME}识别：TikTok\n标题：{video_info['title']}"
            ),
        ),
    )
    if not is_content_enabled(get_target_id(event), "tiktok", "video"):
        return
    if _skip_video_for_duration("TikTok", video_info.get("duration")):
        return

    try:
        target_tik_video_path = await download_ytb_video(
            url,
            CACHE_DIR,
            TIKTOK_PROXY,
            "tiktok",
            media_delivery.video_compress_limit,
        )
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"[TikTok] 视频超过大小限制，已跳过下载和发送：{exc}")
        return
    except RuntimeError as exc:
        await tik.finish(str(exc))

    await send_resolved_video(event, target_tik_video_path, TIKTOK_PROXY)
