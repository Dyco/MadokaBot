from dataclasses import dataclass
from typing import Dict, Optional
from pathlib import Path

from .constants import ResType, SubFolder
from .utils import get_indexed_files


@dataclass(frozen=True)
class ShopDefinition:
    """A hand-written shop category backed directly by an asset directory."""

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
def get_skin_map() -> Dict[str, Path]:
    """Scan the configured enum directory and generate consecutive runtime IDs."""
    return get_indexed_files(
        SKIN_SHOP.type,
        SKIN_SHOP.content,
        prefix=SKIN_SHOP.prefix,
    )


def get_skin_asset_name(skin_key: str) -> Optional[str]:
    """Translate a temporary display key (for example skin06) to its asset name."""
    path = get_skin_map().get(skin_key.strip().lower())
    return path.name if path else None


def get_skin_path(asset_name: str) -> Optional[Path]:
    """Resolve a persisted asset name without depending on its current display number."""
    path = next(
        (path for path in get_skin_map().values() if path.name == asset_name),
        None,
    )
    return path if path and path.is_file() else None
