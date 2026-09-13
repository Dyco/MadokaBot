"""Resolver 下载完成后的本地视频交付。"""

from pathlib import Path
from typing import cast

from nonebot import get_plugin_config, logger
from nonebot.adapters.onebot.v11 import Bot, Event
from nonebot.matcher import current_bot

from ..madoka_bundle.config import config as madoka_config
from ..madoka_bundle.plugins.common import MediaDeliveryMode, media_delivery
from .config import Config
from .core.downloads import download_video

resolver_config = get_plugin_config(Config)
download_proxy = resolver_config.resolver_proxy or madoka_config.proxy


async def send_resolved_video(
    event: Event,
    source: str | Path | None,
) -> None:
    """下载远程视频（如有需要），再交给通用媒体服务发送。"""
    path: Path | None = None
    bot: Bot | None = None
    try:
        bot = cast(Bot, current_bot.get())
        value = str(source) if source is not None else ""
        if value.startswith(("http://", "https://")):
            value = await download_video(
                value,
                download_proxy,
                max_size=media_delivery.video_compress_limit,
            ) or ""
        if not value:
            logger.warning("Resolver 没有获得可发送的视频文件")
            return

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
        finally:
            media_delivery.discard_prepared(media, prepared)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning(f"Resolver 视频无法发送：{exc}")
        if bot is not None:
            await bot.send(event, f"视频无法发送：{exc}")
    except Exception as exc:
        logger.exception(f"Resolver 视频发送失败：{exc}")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
            path.with_name(f"{path.name}.jpg").unlink(missing_ok=True)
