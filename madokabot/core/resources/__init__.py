"""资源目录、类型与文件检索；不依赖消息适配器。"""

from .manager import AssetManager, assets, get_file, get_files, get_indexed_files
from .types import ResourceFolder, ResourceType

__all__ = [
    "AssetManager",
    "ResourceFolder",
    "ResourceType",
    "assets",
    "get_file",
    "get_files",
    "get_indexed_files",
]
