# -*- coding: utf-8 -*-

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
    FIVE_E = "5eplay"  # 5E 段位与平台标识资源目录
    GROUP = "group"  # 群组数据目录
    POKE = "poke"
    SIGN = "sign"
    CHAR = "madoka"
    STEAM = "steam"
