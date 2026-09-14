from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel

from .constants import ResType, SubFolder

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MainConfig(BaseModel):
    assets_path: Path = PROJECT_ROOT / "assets"
    proxy: str | None = None # 代理地址
    video_message_max_mb: float = 95 # 视频消息发送的文件大小上限，单位 MiB
    video_compress_max_mb: float = 300 # 使用FFmpeg压缩的视频上限，单位 MiB
    video_compress_target_mb: float = 90 # FFmpeg压缩后的视频目标大小，单位 MiB
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ffmpeg_timeout: int = 1800 # FFmpeg/FFprobe 单次处理的最长时间，单位秒
    group_file_max_mb: float = 1024 # 允许上传为群文件的大小上限，单位 MiB
    group_file_upload_timeout: int = 3000 # 群文件上传 API 的等待超时，单位秒


class AssetManager:
    def __init__(self, root: Path):
        self.root = root

    def get_dir(self, res_type: ResType, plugin: SubFolder) -> Path:
        """返回资源目录，并在目录尚不存在时创建它。"""
        path = self.root / res_type.value / plugin.value
        path.mkdir(parents=True, exist_ok=True)
        return path


config = get_plugin_config(MainConfig)
assets = AssetManager(config.assets_path)
