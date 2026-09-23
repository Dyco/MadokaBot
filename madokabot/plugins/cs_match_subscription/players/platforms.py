"""玩家战绩平台名称解析。"""

from __future__ import annotations

from .constants import PLATFORM_ALIASES


def normalize_platform(value: str | None) -> str | None:
    """将 5E、5eplay、wm、PW、完美等输入统一为内部平台名称。"""
    if not value:
        return None
    return PLATFORM_ALIASES.get(value.strip().casefold())


def platform_label(platform: str) -> str:
    """返回适合消息和卡片展示的平台名称。"""
    return "5E" if platform == "5e" else "完美世界"
