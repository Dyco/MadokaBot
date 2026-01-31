from enum import Enum

# 资源分类
class ResType(Enum):
    AUDIO = "audio"
    IMAGE = "image"
    FONT = "font"
    JSON = "json"

# 插件子文件名
class SubFolder(Enum):
    POKE = "poke"
    SIGN = "sign"
    CHAR = "madoka"
    STEAM = "steam"