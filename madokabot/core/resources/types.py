from enum import Enum


class ResourceType(Enum):
    """资源类型。"""

    AUDIO = "audio"
    IMAGE = "image"
    FONT = "font"
    JSON = "json"


class ResourceFolder(Enum):
    """资源所属功能的目录名称。"""

    CS = "cs"
    CSTEAM = "csteam"
    PERFECTWORLD = "perfectworld"
    FIVE_E = "5eplay"
    GROUP = "group"
    POKE = "poke"
    SIGN = "sign"
    CHAR = "madoka"
    STEAM = "steam"
