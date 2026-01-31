from pathlib import Path
from pydantic import BaseModel
from nonebot import get_plugin_config
from .constants import ResType, SubFolder

class MainConfig(BaseModel):
    assets_path: Path = Path.cwd() / "assets" #默认资源目录

config = get_plugin_config(MainConfig)

class AssetManager:
    def __init__(self, root: Path):
        self.root = root

    def get_dir(self, res_type: ResType, plugin: SubFolder) -> Path:
        """定位文件夹：assets/{type}/{plugin_name}"""
        path = self.root / res_type.value / plugin.value
        path.mkdir(parents=True, exist_ok=True)
        return path

# 实例化管理器
assets = AssetManager(config.assets_path)