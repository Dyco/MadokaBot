from enum import Enum


class ResType(Enum):
    AUDIO = "audio"
    IMAGE = "image"
    FONT = "font"
    JSON = "json"


class SubFolder(Enum):
    POKE = "poke"
    SIGN = "sign"
    CHAR = "madoka"
    STEAM = "steam"
