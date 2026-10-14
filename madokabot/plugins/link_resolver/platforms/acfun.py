"""acfun 链接解析事件处理器。"""

import re
import shutil
import tempfile
from pathlib import Path

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from madokabot.core.config import config as madoka_config
from madokabot.core.messaging.media import MediaSizeLimitExceeded

from ..commands import resolve_controller, resolve_handler
from ..delivery import media_delivery, send_resolved_video
from ..downloads import (
    CACHE_DIR,
    DownloadBudget,
    ensure_remote_total_within_limit,
)
from ..matchers import (
    ACFUN_PATTERN,
)
from ..matchers import (
    acfun_matcher as acfun,
)
from ..messages import (
    get_resolver_message,
    get_target_id,
    make_forward_nodes,
    send_forward,
)
from ..sources.acfun import (
    download_m3u8_videos,
    merge_ac_file_to_mp4,
    parse_m3u8,
    parse_url,
)
from ..state import is_content_enabled
from .runtime import (
    ACFUN_PROXY,
    GLOBAL_NICKNAME,
)
from .video import (
    _gather_downloads,
    _skip_video_for_duration,
)


@acfun.handle()
@resolve_handler
@resolve_controller
async def ac(bot: Bot, event: GroupMessageEvent) -> None:
    """校验 AcFun 分享地址与作品编号，视频关闭时跳过分片下载。"""
    url_match = re.search(ACFUN_PATTERN, get_resolver_message(event), re.IGNORECASE)
    if not url_match:
        return
    ac_match = re.search(r"(?:[?&]ac=|/v/ac)([1-9]\d*)(?=[/?&#]|$)", url_match[0])
    if not ac_match:
        return
    inputMsg = f"https://www.acfun.cn/v/ac{ac_match[1]}"

    try:
        url_m3u8s, video_name = await parse_url(inputMsg, ACFUN_PROXY)
    except ValueError:
        logger.warning("[ACFun] 未获取到有效视频详情，跳过解析")
        return
    await send_forward(
        bot,
        event,
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(f"{GLOBAL_NICKNAME}识别：猴山\n标题：{video_name}"),
        ),
    )
    if not is_content_enabled(get_target_id(event), "acfun", "video"):
        return
    m3u8_full_urls, ts_names, _, output_file_name, video_duration = await parse_m3u8(
        url_m3u8s,
        ACFUN_PROXY,
        include_duration=True,
    )
    if _skip_video_for_duration("ACFun", video_duration):
        return
    try:
        await ensure_remote_total_within_limit(
            m3u8_full_urls,
            media_delivery.video_compress_limit,
            ACFUN_PROXY,
        )
        budget = DownloadBudget(media_delivery.video_compress_limit)
        work_dir = Path(tempfile.mkdtemp(prefix="acfun-", dir=CACHE_DIR))
        await _gather_downloads(
            *[
                download_m3u8_videos(
                    url,
                    i,
                    work_dir,
                    ACFUN_PROXY,
                    budget,
                )
                for i, url in enumerate(m3u8_full_urls)
            ]
        )
        output_path = await merge_ac_file_to_mp4(
            ts_names,
            output_file_name,
            work_dir=work_dir,
            ffmpeg_path=madoka_config.ffmpeg_path,
            timeout=madoka_config.ffmpeg_timeout,
        )
        if await send_resolved_video(event, output_path, ACFUN_PROXY):
            shutil.rmtree(work_dir, ignore_errors=True)
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"[ACFun] 视频超过大小限制，已跳过下载和发送：{exc}")
        return
    except ValueError as exc:
        await acfun.finish(f"视频无法下载：{exc}")
    except RuntimeError as exc:
        await acfun.finish(f"视频处理失败：{exc}")
