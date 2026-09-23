"""tiktok 链接解析事件处理器。"""

import re

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    CACHE_DIR,
)
from ..matchers import (
    tiktok_matcher as tik,
)
from ..messages import get_resolver_message, make_forward_nodes, send_forward
from ..sources.youtube import download_ytb_video, get_video_info
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
    """
        tiktok解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    url = get_resolver_message(event)

    url_reg = r"(http:|https:)\/\/www.tiktok.com\/[A-Za-z\d._?%&+\-=\/#@]*"
    url_short_reg = r"(http:|https:)\/\/vt.tiktok.com\/[A-Za-z\d._?%&+\-=\/#]*"
    url_short_reg2 = r"(http:|https:)\/\/vm.tiktok.com\/[A-Za-z\d._?%&+\-=\/#]*"

    if "vt.tiktok" in url:
        temp_url = re.search(url_short_reg, url)[0]
        temp_resp = httpx.get(
            temp_url,
            follow_redirects=True,
            proxy=TIKTOK_PROXY,
            trust_env=False,
        )
        url = str(temp_resp.url)
    elif "vm.tiktok" in url:
        temp_url = re.search(url_short_reg2, url)[0]
        temp_resp = httpx.get(
            temp_url,
            headers={"User-Agent": "facebookexternalhit/1.1"},
            follow_redirects=True,
            proxy=TIKTOK_PROXY,
            trust_env=False,
        )
        url = str(temp_resp.url)
        # logger.info(url)
    else:
        url = re.search(url_reg, url)[0]
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
