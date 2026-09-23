from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CoreConfig(BaseModel):
    """资源、媒体处理、消息回应和缓存清理的公共配置。"""

    assets_path: Path = PROJECT_ROOT / "assets"
    proxy: str | None = None  # 代理地址

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ffmpeg_timeout: int = 1800  # FFmpeg/FFprobe 单次处理的最长时间，单位秒
    file_cleanup_retention_hours: float = 12.0  # 通用缓存文件保留时间
    file_cleanup_interval_minutes: float = 60.0  # 通用文件清理间隔
    response_emoji_id: str = "424"  # 普通响应使用的表情
    status_response_emoji_id: str = "86"  # 状态响应开始使用的表情
    status_complete_emoji_id: str = "478"  # 状态响应完成使用的表情


config = get_plugin_config(CoreConfig)
