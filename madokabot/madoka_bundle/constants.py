from enum import Enum


class ResType(Enum):
    AUDIO = "audio"
    IMAGE = "image"
    FONT = "font"
    JSON = "json"


class SubFolder(Enum):
    CS = "cs"
    CSTEAM = "csteam"
    PERFECTWORLD = "perfectworld"  # 完美世界战绩卡片资源目录
    POKE = "poke"
    SIGN = "sign"
    CHAR = "madoka"
    STEAM = "steam"
