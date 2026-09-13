"""OneBot 本地媒体发送、视频压缩与群文件操作。"""

import asyncio
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
import nonebot_plugin_localstore as store

from ...config import config as madoka_config

MIB = 1024 * 1024
VIDEO_SEND_RETENTION_SECONDS = 300
VIDEO_SEND_CACHE_DIR = store.get_cache_dir("madoka_bundle") / "video_send"
VIDEO_SEND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".m4v",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".flv",
        ".mpeg",
        ".mpg",
        ".wmv",
        ".ts",
    }
)


class MediaDeliveryMode(str, Enum):
    VIDEO_MESSAGE = "video_message"
    VIDEO_COMPRESS = "video_compress"
    GROUP_FILE = "group_file"


@dataclass(frozen=True)
class LocalMedia:
    path: Path
    name: str
    size: int
    mode: MediaDeliveryMode

    @property
    def size_mb(self) -> float:
        return self.size / MIB


@dataclass(frozen=True)
class MediaDeliveryResult:
    media: LocalMedia
    response: Any


class MediaDelivery:
    """根据统一大小限制发送视频消息或上传文件。"""

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
        self.video_message_limit = int(video_message_max_mb * MIB)
        self.video_compress_limit = int(video_compress_max_mb * MIB)
        self.video_compress_target = int(video_compress_target_mb * MIB)
        self.group_file_limit = int(group_file_max_mb * MIB)
        self.upload_timeout = upload_timeout
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.ffmpeg_timeout = ffmpeg_timeout
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

        if self.video_compress_target >= self.video_message_limit:
            raise ValueError("视频压缩目标大小必须小于视频消息上限")
        if self.video_compress_limit < self.video_message_limit:
            raise ValueError("视频压缩上限不能小于视频消息上限")

    @staticmethod
    def sanitize_file_name(name: str) -> str:
        name = re.sub(r"[/\\]", "、", name)
        return re.sub(r'[:*?"<>|]', "_", name).strip() or "media"

    @staticmethod
    def is_video(path: str | Path) -> bool:
        return Path(path).suffix.lower() in VIDEO_SUFFIXES

    def inspect(self, path: str | Path, name: str | None = None) -> LocalMedia:
        local_path = Path(path).expanduser().resolve()
        if not local_path.is_file():
            raise FileNotFoundError(f"本地媒体文件不存在：{local_path}")

        size = local_path.stat().st_size
        if size <= 0:
            raise ValueError(f"本地媒体文件为空：{local_path}")
        is_video = self.is_video(local_path)
        if is_video and size > self.video_compress_limit:
            raise ValueError(
                f"视频大小 {size / MIB:.2f} MiB 超过允许下载和处理的上限 "
                f"{self.video_compress_limit / MIB:g} MiB"
            )
        if not is_video and size > self.group_file_limit:
            raise ValueError(
                f"文件大小 {size / MIB:.2f} MiB 超过群文件上限 "
                f"{self.group_file_limit / MIB:g} MiB"
            )

        if is_video and size < self.video_message_limit:
            mode = MediaDeliveryMode.VIDEO_MESSAGE
        elif is_video:
            mode = MediaDeliveryMode.VIDEO_COMPRESS
        else:
            mode = MediaDeliveryMode.GROUP_FILE
        return LocalMedia(
            path=local_path,
            name=self.sanitize_file_name(name or local_path.name),
            size=size,
            mode=mode,
        )

    async def _run_media_command(self, *command: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"找不到媒体处理程序：{command[0]}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.ffmpeg_timeout,
            )
        except asyncio.TimeoutError as exc:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise RuntimeError(
                f"媒体处理超过 {self.ffmpeg_timeout} 秒，已终止：{command[0]}"
            ) from exc
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        if process.returncode:
            reason = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"媒体处理失败[{process.returncode}]：{reason[-1000:]}"
            )
        return stdout.decode("utf-8", errors="replace").strip()

    async def _probe_duration(self, path: Path) -> float:
        output = await self._run_media_command(
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        )
        try:
            duration = float(output)
        except ValueError as exc:
            raise RuntimeError("FFprobe 未能读取视频时长") from exc
        if duration <= 0:
            raise RuntimeError("视频时长无效，无法计算压缩码率")
        return duration

    async def compress_video(self, media: LocalMedia) -> LocalMedia:
        """使用双遍 H.264 编码，将视频压到配置的目标大小附近。"""
        if media.mode is not MediaDeliveryMode.VIDEO_COMPRESS:
            return media

        duration = await self._probe_duration(media.path)
        audio_bitrate_kbps = 96
        target_total_bps = self.video_compress_target * 8 * 0.97 / duration
        video_bitrate_kbps = int(target_total_bps / 1000) - audio_bitrate_kbps
        if video_bitrate_kbps < 100:
            raise RuntimeError("目标大小不足以保留可用的视频码率")

        token = uuid.uuid4().hex
        output_path = media.path.with_name(
            f"{media.path.stem}.compressed-{token[:8]}.mp4"
        )
        passlog_path = media.path.with_name(f"ffmpeg-pass-{token}")
        common_args = (
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(media.path),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-b:v",
            f"{video_bitrate_kbps}k",
            "-passlogfile",
            str(passlog_path),
        )
        try:
            await self._run_media_command(
                self.ffmpeg_path,
                *common_args,
                "-pass",
                "1",
                "-an",
                "-f",
                "null",
                os.devnull,
            )
            await self._run_media_command(
                self.ffmpeg_path,
                *common_args,
                "-pass",
                "2",
                "-map",
                "0:a:0?",
                "-c:a",
                "aac",
                "-b:a",
                f"{audio_bitrate_kbps}k",
                "-movflags",
                "+faststart",
                str(output_path),
            )
            compressed = self.inspect(output_path, f"{media.path.stem}.mp4")
            if compressed.mode is not MediaDeliveryMode.VIDEO_MESSAGE:
                raise RuntimeError(
                    f"压缩结果 {compressed.size_mb:.2f} MiB 仍超过视频消息上限"
                )
            return compressed
        except Exception:
            output_path.unlink(missing_ok=True)
            raise
        finally:
            for pass_file in media.path.parent.glob(f"{passlog_path.name}*"):
                pass_file.unlink(missing_ok=True)

    async def prepare(self, media: LocalMedia) -> LocalMedia:
        if media.mode is MediaDeliveryMode.VIDEO_COMPRESS:
            return await self.compress_video(media)
        return media

    @staticmethod
    def discard_prepared(original: LocalMedia, prepared: LocalMedia) -> None:
        if prepared.path != original.path:
            prepared.path.unlink(missing_ok=True)

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
        try:
            await asyncio.sleep(VIDEO_SEND_RETENTION_SECONDS)
        finally:
            path.unlink(missing_ok=True)

    def _schedule_staged_video_cleanup(self, path: Path) -> None:
        task = asyncio.create_task(self._cleanup_staged_video(path))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def send_video(
        self,
        bot: Bot,
        event: Event,
        media: LocalMedia,
    ) -> Any:
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
        staged = await self._stage_video_for_send(media)
        try:
            response = await bot.send_group_msg(
                group_id=int(group_id),
                message=Message(
                    MessageSegment.video(file=staged.path.as_uri())
                ),
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
        return await bot.call_api(
            "upload_group_file",
            group_id=int(group_id),
            file=str(media.path),
            name=media.name,
            _timeout=timeout or self.upload_timeout,
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
        media = self.inspect(path, name)
        prepared = await self.prepare(media)
        try:
            if prepared.mode is MediaDeliveryMode.VIDEO_MESSAGE:
                response = await self.send_video(bot, event, prepared)
            else:
                response = await self.upload_file(
                    bot, event, prepared, timeout=timeout
                )
            return MediaDeliveryResult(media=media, response=response)
        finally:
            self.discard_prepared(media, prepared)

    async def get_group_files(
        self,
        bot: Bot,
        group_id: str | int,
        folder_id: str | None = None,
    ) -> list[dict[str, Any]]:
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
        response = await bot.call_api(
            "get_group_file_system_info",
            group_id=int(group_id),
        )
        return response if isinstance(response, dict) else {}


media_delivery = MediaDelivery(
    video_message_max_mb=madoka_config.video_message_max_mb,
    video_compress_max_mb=madoka_config.video_compress_max_mb,
    video_compress_target_mb=madoka_config.video_compress_target_mb,
    group_file_max_mb=madoka_config.group_file_max_mb,
    upload_timeout=madoka_config.group_file_upload_timeout,
    ffmpeg_path=madoka_config.ffmpeg_path,
    ffprobe_path=madoka_config.ffprobe_path,
    ffmpeg_timeout=madoka_config.ffmpeg_timeout,
)
