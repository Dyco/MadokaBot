"""CS 插件共用的网络配置工具。"""

from __future__ import annotations

from typing import Any


def resolve_proxy(*candidates: Any) -> str | None:
    """返回第一个有效代理地址，并统一补全协议。"""
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value if "://" in value else f"http://{value}"
    return None
