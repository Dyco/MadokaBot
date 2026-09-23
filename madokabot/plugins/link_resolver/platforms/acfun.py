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
    acfun_matcher as acfun,
)
from ..messages import get_resolver_message, make_forward_nodes, send_forward
from ..sources.acfun import (
    download_m3u8_videos,
    merge_ac_file_to_mp4,
    parse_m3u8,
    parse_url,
)
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
    """
        acfun解析
    :param bot:
    :param event:
    :return:
    """
    # 消息
    inputMsg = get_resolver_message(event)

    # 短号处理
    if "m.acfun.cn" in inputMsg:
        inputMsg = f"https://www.acfun.cn/v/ac{re.search(r'ac=([^&?]*)', inputMsg)[1]}"
    else:
        acfun_match = re.search(
            r"https?://[^\s]+acfun\.cn/[^\s]+", inputMsg, re.IGNORECASE
        )
        if acfun_match:
            inputMsg = acfun_match.group(0)

    url_m3u8s, video_name = parse_url(inputMsg, ACFUN_PROXY)
    await send_forward(
        bot,
        event,
        make_forward_nodes(
            bot.self_id,
            MessageSegment.text(f"{GLOBAL_NICKNAME}识别：猴山\n标题：{video_name}"),
        ),
    )
    m3u8_full_urls, ts_names, _, output_file_name, video_duration = parse_m3u8(
        url_m3u8s,
        ACFUN_PROXY,
        include_duration=True,
    )
    if _skip_video_for_duration("ACFun", video_duration):
        return
    # logger.info(output_folder_name, output_file_name)
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
