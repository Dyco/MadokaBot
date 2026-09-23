from enum import Enum


class ResourceType(Enum):
    """资源类型；成员名称和值用于已有数据，不随目录迁移变更。"""

    AUDIO = "audio"
    IMAGE = "image"
    FONT = "font"
    JSON = "json"


class ResourceFolder(Enum):
    """资源所属功能的目录名称。"""

    CS = "cs"
    CSTEAM = "csteam"
    PERFECTWORLD = "perfectworld"  # 完美世界战绩卡片资源目录
    FIVE_E = "5eplay"  # 5E 段位与平台标识资源目录
    GROUP = "group"  # 群组数据目录
    POKE = "poke"
    SIGN = "sign"
    CHAR = "madoka"
    STEAM = "steam"
