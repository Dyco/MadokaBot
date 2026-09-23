"""本地媒体文件检查和交付类型。"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

MIB = 1024 * 1024
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
    """媒体文件的发送方式。"""

    VIDEO_MESSAGE = "video_message"
    VIDEO_COMPRESS = "video_compress"
    GROUP_FILE = "group_file"


class MediaSizeLimitExceeded(ValueError):
    """媒体文件超过配置的大小限制。"""


@dataclass(frozen=True)
class LocalMedia:
    """记录本地媒体路径、大小和发送方式。"""

    path: Path
    name: str
    size: int
    mode: MediaDeliveryMode

    @property
    def size_mb(self) -> float:
        """返回以 MiB 为单位的媒体大小。"""
        return self.size / MIB


@dataclass(frozen=True)
class MediaDeliveryResult:
    """保存媒体发送前的信息和 OneBot 响应。"""

    media: LocalMedia
    response: Any


class MediaInspector:
    """依据文件大小和格式选择媒体交付方式。"""

    def __init__(
        self,
        video_message_limit: int,
        video_compress_limit: int,
        group_file_limit: int,
    ) -> None:
        """保存媒体大小限制。"""
        self.video_message_limit = video_message_limit
        self.video_compress_limit = video_compress_limit
        self.group_file_limit = group_file_limit

    @staticmethod
    def sanitize_file_name(name: str) -> str:
        """清理上传文件名中的非法字符。"""
        name = re.sub(r"[/\\]", "、", name)
        return re.sub(r'[:*?"<>|]', "_", name).strip() or "media"

    @staticmethod
    def is_video(path: str | Path) -> bool:
        """根据文件扩展名识别视频。"""
        return Path(path).suffix.lower() in VIDEO_SUFFIXES

    def inspect(self, path: str | Path, name: str | None = None) -> LocalMedia:
        """检查本地媒体文件并决定交付方式。"""
        local_path = Path(path).expanduser().resolve()
        if not local_path.is_file():
            raise FileNotFoundError(f"本地媒体文件不存在：{local_path}")

        size = local_path.stat().st_size
        if size <= 0:
            raise ValueError(f"本地媒体文件为空：{local_path}")
        is_video = self.is_video(local_path)
        if is_video and size > self.video_compress_limit:
            raise MediaSizeLimitExceeded(
                f"视频大小 {size / MIB:.2f} MiB 超过允许下载和处理的上限 "
                f"{self.video_compress_limit / MIB:g} MiB"
            )
        if not is_video and size > self.group_file_limit:
            raise MediaSizeLimitExceeded(
                f"文件大小 {size / MIB:.2f} MiB 超过群文件上限 "
                f"{self.group_file_limit / MIB:g} MiB"
            )

        if is_video and size <= self.video_message_limit:
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

    @staticmethod
    def discard_prepared(original: LocalMedia, prepared: LocalMedia) -> None:
        """清理转码生成的临时文件。"""
        if prepared.path != original.path:
            prepared.path.unlink(missing_ok=True)
