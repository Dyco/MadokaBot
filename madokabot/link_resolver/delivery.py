"""Resolver 下载完成后的本地视频交付。"""

from pathlib import Path
from typing import cast

from nonebot import get_plugin_config, logger
from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.matcher import current_bot

from ..madoka_bundle.config import config as madoka_config
from ..madoka_bundle.plugins.common import (
    MediaDelivery,
    MediaSizeLimitExceeded,
)
from .config import Config
from .core.downloads import download_video
from .state import (
    current_resolver_key,
    current_resolver_target,
    is_content_enabled,
)

resolver_config = get_plugin_config(Config)
media_delivery = MediaDelivery(
    video_message_max_mb=resolver_config.video_message_max_mb,
    video_compress_max_mb=resolver_config.video_compress_max_mb,
    video_compress_target_mb=resolver_config.video_compress_target_mb,
    group_file_max_mb=resolver_config.group_file_max_mb,
    upload_timeout=resolver_config.group_file_upload_timeout,
    ffmpeg_path=madoka_config.ffmpeg_path,
    ffprobe_path=madoka_config.ffprobe_path,
    ffmpeg_timeout=madoka_config.ffmpeg_timeout,
)


async def send_resolved_video(
    event: Event,
    source: str | Path | None,
    proxy: str | None = None,
) -> bool:
    """下载并发送视频；发送失败时保留文件，不降级为文件上传。"""
    path: Path | None = None
    bot: Bot | None = None
    sent = False
    try:
        bot = cast(Bot, current_bot.get())
        resolver_key = current_resolver_key.get()
        target_id = current_resolver_target.get()
        if (
            resolver_key is not None
            and not is_content_enabled(target_id, resolver_key, "video")
        ):
            logger.info(
                f"目标 {target_id} 已关闭 {resolver_key} 的视频内容，跳过发送"
            )
            return False

        value = str(source) if source is not None else ""
        if value.startswith(("http://", "https://")):
            value = await download_video(
                value,
                proxy,
                max_size=media_delivery.video_compress_limit,
            ) or ""
        if not value:
            logger.warning("Resolver 没有获得可发送的视频文件")
            return False

        path = Path(value)
        media = media_delivery.inspect(path)
        prepared = await media_delivery.prepare(media)
        await media_delivery.send_video(bot, event, prepared)
        sent = True
        try:
            media_delivery.discard_prepared(media, prepared)
        except OSError as exc:
            logger.warning(f"Resolver 清理转码临时文件失败：{exc}")
    except MediaSizeLimitExceeded as exc:
        logger.warning(f"Resolver 视频超过大小限制，已跳过发送：{exc}")
    except (FileNotFoundError, ValueError) as exc:
        logger.warning(f"Resolver 视频无法发送：{exc}")
        if bot is not None:
            await bot.send(event, f"视频无法发送：{exc}")
    except Exception as exc:
        logger.exception(
            f"Resolver 视频发送失败，文件已保留[{path}]：{exc}"
        )
    finally:
        if sent and path is not None:
            try:
                path.unlink(missing_ok=True)
                path.with_name(f"{path.name}.jpg").unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(f"Resolver 成功发送后清理文件失败[{path}]：{exc}")
    return sent
