"""CS 赛事插件使用的通用资源。"""

from __future__ import annotations

from pathlib import Path

from madokabot.core.resources import ResourceType, ResourceFolder, get_file


CS_FONT_FILENAME = "SourceHanSansSC.woff2"
cs_font_path = get_file(ResourceType.FONT, ResourceFolder.CS, CS_FONT_FILENAME)
font_regular_path = cs_font_path
font_light_path = cs_font_path
font_bold_path = cs_font_path
event_font_path = cs_font_path


def _as_uri(path: Path | None) -> str:
    """本地资源URI转换方法。"""
    return path.resolve().as_uri() if path is not None else ""


def font_context() -> dict[str, str]:
    """字体资源参数。"""
    return {
        "font_regular_path": _as_uri(font_regular_path),
        "font_light_path": _as_uri(font_light_path),
        "font_bold_path": _as_uri(font_bold_path),
    }


def event_font_context() -> dict[str, str]:
    """返回赛事列表模板使用的字体 URI。"""
    return {"event_font_path": _as_uri(event_font_path)}


__all__ = [
    "CS_FONT_FILENAME",
    "cs_font_path",
    "event_font_context",
    "event_font_path",
    "font_bold_path",
    "font_context",
    "font_light_path",
    "font_regular_path",
]
