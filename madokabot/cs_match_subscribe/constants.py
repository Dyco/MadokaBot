"""CS 赛事插件使用的通用资源。"""

from __future__ import annotations

from pathlib import Path

from ..madoka_bundle.constants import ResType, SubFolder
from ..madoka_bundle.utils import get_file


# 资源统一放在 assets/font/cs，由通用资源管理器解析路径。
font_regular_path = get_file(ResType.FONT, SubFolder.CS, "Inter-Regular.woff2")
font_light_path = (
    get_file(ResType.FONT, SubFolder.CS, "Inter-Light.woff2")
    or font_regular_path
)
font_bold_path = get_file(ResType.FONT, SubFolder.CS, "Inter-Bold.woff2")


def font_context() -> dict[str, str]:
    """返回 Chromium CSS 可直接使用的本地字体 URI。"""

    def as_uri(path: Path | None) -> str:
        return path.resolve().as_uri() if path is not None else ""

    return {
        "font_regular_path": as_uri(font_regular_path),
        "font_light_path": as_uri(font_light_path),
        "font_bold_path": as_uri(font_bold_path),
    }


__all__ = [
    "font_bold_path",
    "font_context",
    "font_light_path",
    "font_regular_path",
]
