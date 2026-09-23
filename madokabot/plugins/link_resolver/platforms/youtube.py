"""youtube 链接解析事件处理器。"""

import re
from pathlib import Path

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    CACHE_DIR,
    download_image,
)
from ..matchers import (
    youtube_matcher as y2b,
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
    YOUTUBE_PROXY,
)
from .video import (
    _skip_video_for_duration,
)


@y2b.handle()
@resolve_handler
@resolve_controller
async def youtube(bot: Bot, event: GroupMessageEvent):
    """解析 YouTube 视频分享链接。"""
    msg_url = re.search(
        r"(?:https?://)?(?:www\.)?youtube\.com/[A-Za-z\d._?%&+\-=/#]*"
        r"|(?:https?://)?youtu\.be/[A-Za-z\d._?%&+\-=/#]*",
        get_resolver_message(event),
    )[0]

    try:
        video_info = await get_video_info(msg_url, YOUTUBE_PROXY)
    except RuntimeError as exc:
        await y2b.finish(str(exc))

    description = re.sub(
        r"\r\n?",
        "\n",
        video_info["description"],
    ).strip()
    if len(description) > 3000:
        description = description[:3000] + "…"
    description = description or "暂无简介"

    cover_path: str | None = None
    thumbnail_url = video_info["thumbnail"]
    # 图片关闭时不下载封面，避免产生无意义的代理请求。
    if thumbnail_url and is_content_enabled(get_target_id(event), "youtube", "image"):
        try:
            cover_path = await download_image(
                thumbnail_url,
                proxy=YOUTUBE_PROXY,
            )
        except Exception as exc:
            logger.warning(f"[YouTube] 封面下载失败，跳过封面：{exc}")

    forward_nodes: list[MessageSegment] = []
    if cover_path:
        forward_nodes.append(
            make_forward_nodes(
                bot.self_id,
                MessageSegment.image(
                    file=Path(cover_path).resolve().as_uri(),
                ),
            )
        )
    forward_nodes.append(
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(
                f"{GLOBAL_NICKNAME}识别：油管\n"
                f"标题：{video_info['title']}\n"
                f"简介：{description}"
            ),
        )
    )
    try:
        await send_forward(bot, event, forward_nodes)
    finally:
        if cover_path:
            Path(cover_path).unlink(missing_ok=True)

    if _skip_video_for_duration("YouTube", video_info.get("duration")):
        return

    try:
        target_ytb_video_path = await download_ytb_video(
            msg_url,
            CACHE_DIR,
            YOUTUBE_PROXY,
            max_size=media_delivery.video_compress_limit,
        )
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"[YouTube] 视频超过大小限制，已跳过下载和发送：{exc}")
        return
    except RuntimeError as exc:
        await y2b.finish(str(exc))

    await send_resolved_video(event, target_ytb_video_path, YOUTUBE_PROXY)
