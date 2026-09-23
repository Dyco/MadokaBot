"""CS 赛事插件使用的通用资源。"""

from __future__ import annotations

from pathlib import Path

from madokabot.core.resources import ResourceType, ResourceFolder, get_file


# 资源统一放在 assets/font/cs，由通用资源管理器解析路径。
# Source Han Sans SC 是可变字体，因此常规、细体、粗体和赛事页面
# 都复用同一个字体文件，由 CSS 的 font-weight 选择具体字重。
CS_FONT_FILENAME = "SourceHanSansSC.woff2"
cs_font_path = get_file(ResourceType.FONT, ResourceFolder.CS, CS_FONT_FILENAME)
font_regular_path = cs_font_path
font_light_path = cs_font_path
font_bold_path = cs_font_path
event_font_path = cs_font_path


def _as_uri(path: Path | None) -> str:
    """将本地资源路径转换为 Chromium 可读取的 URI。"""
    return path.resolve().as_uri() if path is not None else ""


def font_context() -> dict[str, str]:
    """返回 Chromium CSS 可直接使用的本地字体 URI。"""
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
