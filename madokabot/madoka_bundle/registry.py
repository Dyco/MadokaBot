

from typing import Dict
from pathlib import Path

from .constants import ResType, SubFolder
from .utils import get_indexed_files

#加载资源字典
SKIN_MAP: Dict[str, Path] = get_indexed_files(
    ResType.IMAGE,
    SubFolder.CHAR,
    prefix="skin"
)

DEFAULT_SKIN = "skin01"