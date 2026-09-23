"""统一媒体交付入口；文件检查、转码和 OneBot 发送各由独立模块负责。"""

from pathlib import Path
from typing import Any

from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment

from madokabot.core.config import config as madoka_config

from .media_ffmpeg import MediaProcessor
from .media_files import (
    MIB,
    VIDEO_SUFFIXES,
    LocalMedia,
    MediaDeliveryMode,
    MediaDeliveryResult,
    MediaInspector,
    MediaSizeLimitExceeded,
)
from .media_onebot import (
    VIDEO_SEND_CACHE_DIR,
    VIDEO_SEND_RETENTION_SECONDS,
    OneBotMediaSender,
)

__all__ = (
    "MIB",
    "VIDEO_SUFFIXES",
    "VIDEO_SEND_CACHE_DIR",
    "VIDEO_SEND_RETENTION_SECONDS",
    "LocalMedia",
    "MediaDelivery",
    "MediaDeliveryMode",
    "MediaDeliveryResult",
    "MediaInspector",
    "MediaProcessor",
    "MediaSizeLimitExceeded",
    "OneBotMediaSender",
    "media_delivery",
)


class MediaDelivery:
    """按统一配置检查、处理并发送媒体。"""

    def __init__(
        self,
        video_message_max_mb: float,
        video_compress_max_mb: float,
        video_compress_target_mb: float,
        group_file_max_mb: float,
        upload_timeout: int,
        ffmpeg_path: str,
        ffprobe_path: str,
        ffmpeg_timeout: int,
    ) -> None:
        """初始化文件检查、视频处理和 OneBot 发送组件。"""
        self.video_message_limit = int(video_message_max_mb * MIB)
        self.video_compress_limit = int(video_compress_max_mb * MIB)
        self.video_compress_target = int(video_compress_target_mb * MIB)
        self.group_file_limit = int(group_file_max_mb * MIB)
        self.upload_timeout = upload_timeout
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.ffmpeg_timeout = ffmpeg_timeout

        if self.video_compress_target >= self.video_message_limit:
            raise ValueError("视频压缩目标大小必须小于视频消息上限")
        if self.video_compress_limit < self.video_message_limit:
            raise ValueError("视频压缩上限不能小于视频消息上限")

        self.inspector = MediaInspector(
            self.video_message_limit,
            self.video_compress_limit,
            self.group_file_limit,
        )
        self.processor = MediaProcessor(
            self.inspector,
            self.video_compress_target,
            ffmpeg_path,
            ffprobe_path,
            ffmpeg_timeout,
        )
        self.sender = OneBotMediaSender(upload_timeout)

    @staticmethod
    def sanitize_file_name(name: str) -> str:
        """清理上传文件名中的非法字符。"""
        return MediaInspector.sanitize_file_name(name)

    @staticmethod
    def is_video(path: str | Path) -> bool:
        """根据扩展名识别视频。"""
        return MediaInspector.is_video(path)

    def inspect(self, path: str | Path, name: str | None = None) -> LocalMedia:
        """检查文件并选择交付方式。"""
        return self.inspector.inspect(path, name)

    async def compress_video(self, media: LocalMedia) -> LocalMedia:
        """压缩超过视频消息大小限制的文件。"""
        return await self.processor.compress_video(media)

    async def prepare(self, media: LocalMedia) -> LocalMedia:
        """准备适合发送的视频编码。"""
        return await self.processor.prepare(media)

    @staticmethod
    def discard_prepared(original: LocalMedia, prepared: LocalMedia) -> None:
        """清理转码生成的临时文件。"""
        MediaInspector.discard_prepared(original, prepared)

    async def send_video(self, bot: Bot, event: Event, media: LocalMedia) -> Any:
        """通过 OneBot 发送视频消息。"""
        return await self.sender.send_video(bot, event, media)

    async def prepare_video_segment(
        self,
        path: str | Path,
        name: str | None = None,
    ) -> MessageSegment:
        """准备可嵌入普通消息或合并转发的视频消息段。"""
        media = self.inspect(path, name)
        if media.mode is MediaDeliveryMode.GROUP_FILE:
            raise ValueError(f"文件不是可发送的视频：{media.path}")

        prepared = await self.prepare(media)
        try:
            staged = await self.sender._stage_video_for_send(prepared)
        finally:
            self.discard_prepared(media, prepared)

        self.sender._schedule_staged_video_cleanup(staged.path)
        return MessageSegment.video(file=staged.path.as_uri())

    async def send_group_video(
        self, bot: Bot, group_id: str | int, media: LocalMedia
    ) -> Any:
        """通过 OneBot 发送群视频消息。"""
        return await self.sender.send_group_video(bot, group_id, media)

    async def upload_file(
        self,
        bot: Bot,
        event: Event,
        media: LocalMedia,
        *,
        timeout: int | None = None,
    ) -> Any:
        """按事件类型上传文件。"""
        return await self.sender.upload_file(bot, event, media, timeout=timeout)

    async def upload_group_file(
        self,
        bot: Bot,
        group_id: str | int,
        media: LocalMedia,
        *,
        timeout: int | None = None,
    ) -> Any:
        """通过 OneBot 上传群文件。"""
        return await self.sender.upload_group_file(
            bot, group_id, media, timeout=timeout
        )

    async def deliver(
        self,
        bot: Bot,
        event: Event,
        path: str | Path,
        *,
        name: str | None = None,
        timeout: int | None = None,
    ) -> MediaDeliveryResult:
        """检查、准备并发送媒体，结束后清理转码文件。"""
        media = self.inspect(path, name)
        prepared = await self.prepare(media)
        try:
            if prepared.mode is MediaDeliveryMode.VIDEO_MESSAGE:
                response = await self.send_video(bot, event, prepared)
            else:
                response = await self.upload_file(bot, event, prepared, timeout=timeout)
            return MediaDeliveryResult(media=media, response=response)
        finally:
            self.discard_prepared(media, prepared)

    async def get_group_files(
        self, bot: Bot, group_id: str | int, folder_id: str | None = None
    ) -> list[dict[str, Any]]:
        """读取群目录中的文件列表。"""
        return await self.sender.get_group_files(bot, group_id, folder_id)

    async def find_same_group_file(
        self,
        bot: Bot,
        group_id: str | int,
        file_name: str,
        file_size: int,
        folder_id: str | None = None,
    ) -> dict[str, Any] | None:
        """查找同名同大小的群文件。"""
        return await self.sender.find_same_group_file(
            bot, group_id, file_name, file_size, folder_id
        )

    async def get_group_file_system_info(
        self, bot: Bot, group_id: str | int
    ) -> dict[str, Any]:
        """读取群文件系统信息。"""
        return await self.sender.get_group_file_system_info(bot, group_id)


media_delivery = MediaDelivery(
    video_message_max_mb=95,
    video_compress_max_mb=300,
    video_compress_target_mb=90,
    group_file_max_mb=1024,
    upload_timeout=3000,
    ffmpeg_path=madoka_config.ffmpeg_path,
    ffprobe_path=madoka_config.ffprobe_path,
    ffmpeg_timeout=madoka_config.ffmpeg_timeout,
)
