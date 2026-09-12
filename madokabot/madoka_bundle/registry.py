from dataclasses import dataclass
from pathlib import Path

from .constants import ResType, SubFolder
from .utils import get_indexed_files


@dataclass(frozen=True)
class ShopDefinition:
    """由资源目录直接提供商品的手写商店分类。"""

    type: ResType
    content: SubFolder
    price: int
    prefix: str


SKIN_SHOP = ShopDefinition(
    type=ResType.IMAGE,
    content=SubFolder.CHAR,
    price=50,
    prefix="skin",
)


def get_skin_map() -> dict[str, Path]:
    """扫描立绘目录并生成连续的运行时编号。"""
    return get_indexed_files(
        SKIN_SHOP.type,
        SKIN_SHOP.content,
        prefix=SKIN_SHOP.prefix,
    )


def get_skin_path(asset_name: str) -> Path | None:
    """根据持久化文件名查找立绘，不依赖当前展示编号。"""
    path = next(
        (path for path in get_skin_map().values() if path.name == asset_name),
        None,
    )
    return path if path is not None and path.is_file() else None
