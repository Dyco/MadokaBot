"""FFprobe 检查及 FFmpeg 视频转换。"""

import asyncio
import json
import os
import uuid
from pathlib import Path

from nonebot import logger

from .media_files import LocalMedia, MediaDeliveryMode, MediaInspector


class MediaProcessor:
    """准备可发送的视频文件。"""

    def __init__(
        self,
        inspector: MediaInspector,
        video_compress_target: int,
        ffmpeg_path: str,
        ffprobe_path: str,
        ffmpeg_timeout: int,
    ) -> None:
        """保存文件检查器与媒体处理配置。"""
        self.inspector = inspector
        self.video_compress_target = video_compress_target
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.ffmpeg_timeout = ffmpeg_timeout

    async def _run_media_command(self, *command: str) -> str:
        """执行媒体处理命令并读取输出。"""
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
            raise RuntimeError(f"媒体处理失败[{process.returncode}]：{reason[-1000:]}")
        return stdout.decode("utf-8", errors="replace").strip()

    async def _probe_duration(self, path: Path) -> float:
        """读取视频时长。"""
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

    async def _probe_video_codecs(
        self,
        path: Path,
    ) -> tuple[str, str, str | None]:
        """读取视频和音频编码。"""
        output = await self._run_media_command(
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,pix_fmt",
            "-of",
            "json",
            str(path),
        )
        try:
            streams = json.loads(output).get("streams") or []
        except (AttributeError, json.JSONDecodeError) as exc:
            raise RuntimeError("FFprobe 未能读取视频流信息") from exc

        video_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            raise RuntimeError("媒体文件中没有视频流")
        audio_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "audio"),
            None,
        )
        return (
            str(video_stream.get("codec_name") or "").lower(),
            str(video_stream.get("pix_fmt") or "").lower(),
            (
                str(audio_stream.get("codec_name") or "").lower()
                if audio_stream
                else None
            ),
        )

    @staticmethod
    def _is_video_message_compatible(
        media: LocalMedia,
        video_codec: str,
        pixel_format: str,
        audio_codec: str | None,
    ) -> bool:
        """判断编码是否适合 OneBot 视频消息。"""
        return (
            media.path.suffix.lower() == ".mp4"
            and video_codec == "h264"
            and pixel_format in {"yuv420p", "yuvj420p"}
            and audio_codec in {None, "aac"}
        )

    async def _transcode_video_message(self, media: LocalMedia) -> LocalMedia:
        """将不兼容的视频转换为 QQ 视频消息常用的 H.264/AAC。"""
        output_path = media.path.with_name(
            f"{media.path.stem}.compatible-{uuid.uuid4().hex[:8]}.mp4"
        )
        output_name = f"{Path(media.name).stem}.mp4"
        try:
            await self._run_media_command(
                self.ffmpeg_path,
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(media.path),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(output_path),
            )
            converted = self.inspector.inspect(output_path, output_name)
            if converted.mode is MediaDeliveryMode.VIDEO_COMPRESS:
                try:
                    return await self.compress_video(converted)
                finally:
                    output_path.unlink(missing_ok=True)
            return converted
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

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
            compressed = self.inspector.inspect(output_path, f"{media.path.stem}.mp4")
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
        """按媒体类型决定是否需要转码。"""
        if media.mode is MediaDeliveryMode.VIDEO_COMPRESS:
            return await self.compress_video(media)
        if media.mode is MediaDeliveryMode.VIDEO_MESSAGE:
            video_codec, pixel_format, audio_codec = await self._probe_video_codecs(
                media.path
            )
            if not self._is_video_message_compatible(
                media,
                video_codec,
                pixel_format,
                audio_codec,
            ):
                logger.info(
                    "视频编码不适合直接发送，开始转换为 H.264/AAC："
                    f"video={video_codec or 'unknown'}, "
                    f"audio={audio_codec or 'none'}, "
                    f"pix_fmt={pixel_format or 'unknown'}"
                )
                return await self._transcode_video_message(media)
        return media
