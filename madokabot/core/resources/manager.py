from pathlib import Path

from ..config import config
from .types import ResourceFolder, ResourceType


class AssetManager:
    """管理各功能使用的资源目录。"""

    def __init__(self, root: Path):
        """保存资源根目录。"""
        self.root = root

    def get_dir(self, res_type: ResourceType, plugin: ResourceFolder) -> Path:
        """资源目录获取方法。"""
        path = self.root / res_type.value / plugin.value
        path.mkdir(parents=True, exist_ok=True)
        return path


assets = AssetManager(config.assets_path)


def get_files(res_type: ResourceType, plugin: ResourceFolder) -> list[Path]:
    """获取目录下所有非隐藏文件。"""
    directory = assets.get_dir(res_type, plugin)
    return [
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    ]


def get_file(res_type: ResourceType, plugin: ResourceFolder, name: str) -> Path | None:
    """资源文件查询方法。"""
    path = assets.get_dir(res_type, plugin) / name
    return path if path.is_file() else None


def get_indexed_files(
    res_type: ResourceType,
    plugin: ResourceFolder,
    prefix: str = "image",
) -> dict[str, Path]:
    """资源文件索引方法。"""
    files = sorted(get_files(res_type, plugin))
    return {f"{prefix}{index:02d}": path for index, path in enumerate(files, start=1)}
