"""OneBot 视频暂存、消息发送和群文件接口。"""

import asyncio
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as store
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)

from madokabot.core.files.cleanup import register_cleanup_path

from .media_files import LocalMedia

VIDEO_SEND_RETENTION_SECONDS = 300
# 沿用历史缓存目录，避免迁移后遗留正在使用的媒体文件。
VIDEO_SEND_CACHE_DIR = store.get_cache_dir("madoka_bundle") / "video_send"
VIDEO_SEND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
register_cleanup_path("common-video-send", VIDEO_SEND_CACHE_DIR)


class OneBotMediaSender:
    """向 OneBot 发送视频与文件，并管理视频暂存。"""

    def __init__(self, upload_timeout: int) -> None:
        """保存上传超时并跟踪暂存清理任务。"""
        self.upload_timeout = upload_timeout
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def _stage_video_for_send(self, media: LocalMedia) -> LocalMedia:
        """为 OneBot 保留独立文件，避免发送端尚未读取时源文件已被清理。"""
        staged_path = VIDEO_SEND_CACHE_DIR / f"{uuid.uuid4().hex}{media.path.suffix}"
        try:
            await asyncio.to_thread(os.link, media.path, staged_path)
        except OSError:
            await asyncio.to_thread(shutil.copy2, media.path, staged_path)
        return LocalMedia(
            path=staged_path,
            name=media.name,
            size=media.size,
            mode=media.mode,
        )

    async def _cleanup_staged_video(self, path: Path) -> None:
        """延时清理已暂存的视频。"""
        try:
            await asyncio.sleep(VIDEO_SEND_RETENTION_SECONDS)
        finally:
            path.unlink(missing_ok=True)

    def _schedule_staged_video_cleanup(self, path: Path) -> None:
        """安排暂存视频的清理任务。"""
        task = asyncio.create_task(self._cleanup_staged_video(path))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def send_video(
        self,
        bot: Bot,
        event: Event,
        media: LocalMedia,
    ) -> Any:
        """通过 OneBot 发送群或私聊视频消息。"""
        staged = await self._stage_video_for_send(media)
        try:
            message = MessageSegment.video(file=staged.path.as_uri())
            if isinstance(event, GroupMessageEvent):
                response = await bot.send_group_msg(
                    group_id=event.group_id,
                    message=Message(message),
                )
            elif isinstance(event, PrivateMessageEvent):
                response = await bot.send_private_msg(
                    user_id=event.user_id,
                    message=Message(message),
                )
            else:
                raise TypeError("当前事件不支持视频消息")
        except Exception:
            staged.path.unlink(missing_ok=True)
            raise
        self._schedule_staged_video_cleanup(staged.path)
        return response

    async def send_group_video(
        self,
        bot: Bot,
        group_id: str | int,
        media: LocalMedia,
    ) -> Any:
        """通过 OneBot 发送群视频消息。"""
        staged = await self._stage_video_for_send(media)
        try:
            response = await bot.send_group_msg(
                group_id=int(group_id),
                message=Message(MessageSegment.video(file=staged.path.as_uri())),
            )
        except Exception:
            staged.path.unlink(missing_ok=True)
            raise
        self._schedule_staged_video_cleanup(staged.path)
        return response

    async def upload_file(
        self,
        bot: Bot,
        event: Event,
        media: LocalMedia,
        *,
        timeout: int | None = None,
    ) -> Any:
        """按事件类型上传媒体文件。"""
        if isinstance(event, GroupMessageEvent):
            return await self.upload_group_file(
                bot,
                event.group_id,
                media,
                timeout=timeout,
            )
        if isinstance(event, PrivateMessageEvent):
            return await bot.call_api(
                "upload_private_file",
                user_id=event.user_id,
                file=str(media.path),
                name=media.name,
                _timeout=timeout or self.upload_timeout,
            )
        raise TypeError("当前事件不支持文件上传")

    async def upload_group_file(
        self,
        bot: Bot,
        group_id: str | int,
        media: LocalMedia,
        *,
        timeout: int | None = None,
    ) -> Any:
        """上传群文件。"""
        return await bot.call_api(
            "upload_group_file",
            group_id=int(group_id),
            file=str(media.path),
            name=media.name,
            _timeout=timeout or self.upload_timeout,
        )

    async def get_group_files(
        self,
        bot: Bot,
        group_id: str | int,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """读取群目录中的文件列表。"""
        if folder_id and folder_id != "/":
            response = await bot.call_api(
                "get_group_files_by_folder",
                group_id=int(group_id),
                folder_id=folder_id,
            )
        else:
            response = await bot.call_api(
                "get_group_root_files",
                group_id=int(group_id),
            )
        if not isinstance(response, dict) or not isinstance(
            response.get("files"), list
        ):
            return []
        return [item for item in response["files"] if isinstance(item, dict)]

    async def find_same_group_file(
        self,
        bot: Bot,
        group_id: str | int,
        file_name: str,
        file_size: int,
        folder_id: str | None = None,
    ) -> dict[str, Any] | None:
        """查找同名同大小的群文件。"""
        for remote_file in await self.get_group_files(bot, group_id, folder_id):
            try:
                remote_size = int(remote_file.get("file_size", -1))
            except (TypeError, ValueError):
                continue
            if (
                str(remote_file.get("file_name") or "") == file_name
                and remote_size == file_size
            ):
                return remote_file
        return None

    async def get_group_file_system_info(
        self,
        bot: Bot,
        group_id: str | int,
    ) -> dict[str, Any]:
        """读取群文件系统信息。"""
        response = await bot.call_api(
            "get_group_file_system_info",
            group_id=int(group_id),
        )
        return response if isinstance(response, dict) else {}
