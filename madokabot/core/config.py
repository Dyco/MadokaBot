from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CoreConfig(BaseModel):
    """资源、媒体处理、消息回应和缓存清理的公共配置。"""

    assets_path: Path = PROJECT_ROOT / "assets"
    proxy: str | None = None

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ffmpeg_timeout: int = 1800  # 单位：秒
    file_cleanup_retention_hours: float = 12.0
    file_cleanup_interval_minutes: float = 60.0
    response_emoji_id: str = "424"
    status_response_emoji_id: str = "86"
    status_complete_emoji_id: str = "478"


config = get_plugin_config(CoreConfig)
