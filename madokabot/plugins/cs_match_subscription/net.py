"""CS 插件共用的网络配置工具。"""

from __future__ import annotations

from typing import Any

import httpx


class ResponseTooLargeError(ValueError):
    """远程响应超过允许的内存预算。"""


async def read_limited_response(response: httpx.Response, limit: int) -> bytes:
    """流式读取并限制解压后的大小，不能先读完整个响应再检查。"""
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit:
        raise ResponseTooLargeError(f"响应超过 {limit} 字节限制")
    content = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
        if len(content) + len(chunk) > limit:
            raise ResponseTooLargeError(f"响应超过 {limit} 字节限制")
        content.extend(chunk)
    return bytes(content)


def resolve_proxy(*candidates: Any) -> str | None:
    """返回第一个有效代理地址，并统一补全协议。"""
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value if "://" in value else f"http://{value}"
    return None
