"""Resolver 下载完成后的本地视频交付。"""

from pathlib import Path
from typing import cast

from nonebot import get_plugin_config, logger
from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.matcher import current_bot

from ..madoka_bundle.config import config as madoka_config
from ..madoka_bundle.plugins.common import (
    MediaDelivery,
    MediaDeliveryMode,
    MediaSizeLimitExceeded,
)
from .config import Config
from .core.downloads import download_video

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
    """下载并发送视频；只有发送成功后才删除本地文件。"""
    path: Path | None = None
    bot: Bot | None = None
    sent = False
    try:
        bot = cast(Bot, current_bot.get())
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
        try:
            if prepared.mode is MediaDeliveryMode.VIDEO_MESSAGE:
                await media_delivery.send_video(bot, event, prepared)
            else:
                await media_delivery.upload_file(bot, event, prepared)
        except Exception:
            if prepared.mode is not MediaDeliveryMode.VIDEO_MESSAGE:
                raise
            logger.warning("视频消息发送失败，尝试改为上传文件")
            await media_delivery.upload_file(bot, event, prepared)
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
