

from typing import Dict
from pathlib import Path

from .constants import ResType, SubFolder
from .utils import get_indexed_files
from .config import config

#加载资源字典
SKIN_MAP: Dict[str, Path] = get_indexed_files(
    ResType.IMAGE,
    SubFolder.CHAR,
    prefix="skin"
)
SKIN_PRICE_MAP: Dict[str, int] = {skin_key: config.skincost for skin_key in SKIN_MAP}

DEFAULT_SKIN = "skin01"
