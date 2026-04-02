from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel

from .constants import ResType, SubFolder

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MainConfig(BaseModel):
    assets_path: Path = PROJECT_ROOT / "assets"
    skincost: int = 50


class AssetManager:
    def __init__(self, root: Path):
        self.root = root

    def get_dir(self, res_type: ResType, plugin: SubFolder) -> Path:
        """Locate assets/{type}/{plugin_name} and ensure it exists."""
        path = self.root / res_type.value / plugin.value
        path.mkdir(parents=True, exist_ok=True)
        return path


config = get_plugin_config(MainConfig)
assets = AssetManager(config.assets_path)
