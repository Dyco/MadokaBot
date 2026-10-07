from dataclasses import dataclass
from pathlib import Path

from madokabot.core.resources import ResourceType, ResourceFolder, get_indexed_files


@dataclass(frozen=True)
class ShopDefinition:
    """资源商店分类。"""

    type: ResourceType
    content: ResourceFolder
    price: int
    prefix: str


SKIN_SHOP = ShopDefinition(
    type=ResourceType.IMAGE,
    content=ResourceFolder.CHAR,
    price=50,
    prefix="skin",
)


def get_skin_map() -> dict[str, Path]:
    """立绘目录索引方法。"""
    return get_indexed_files(
        SKIN_SHOP.type,
        SKIN_SHOP.content,
        prefix=SKIN_SHOP.prefix,
    )


def get_skin_path(asset_name: str) -> Path | None:
    """立绘文件查询方法。"""
    path = next(
        (path for path in get_skin_map().values() if path.name == asset_name),
        None,
    )
    return path if path is not None and path.is_file() else None
