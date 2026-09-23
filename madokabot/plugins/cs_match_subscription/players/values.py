"""平台响应字段的类型转换。"""

from __future__ import annotations

from typing import Any

from .models import PlayerStatsError


def as_dict(value: Any) -> dict[str, Any]:
    """只保留字典类型的接口字段。"""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """只保留列表类型的接口字段。"""
    return value if isinstance(value, list) else []


def first_value(source: dict[str, Any], *keys: str) -> Any:
    """按候选键读取第一个非空接口字段。"""
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def as_float(value: Any) -> float | None:
    """把接口数字转换为浮点数。"""
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    """把接口数字转换为整数。"""
    number = as_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (OverflowError, ValueError):
        return None


def parse_steam_id(value: Any) -> int | None:
    """无损解析 64 位 SteamID，避免经过 float 导致低位数字被舍入。"""
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    raw = str(value).strip()
    if not raw.isdigit():
        return None
    try:
        steam_id = int(raw, 10)
    except ValueError:
        return None
    return steam_id if steam_id > 0 else None


def parse_pw_steam_id(value: str) -> int:
    """解析完美查询用的 32 位 AccountID 或 64 位 SteamID。"""
    raw = value.strip()
    if not raw.isascii() or not raw.isdigit():
        raise PlayerStatsError("完美平台 Steam ID 必须是纯数字")
    if len(raw) == 10:
        account_id = int(raw)
        if not 0 < account_id <= 0xFFFFFFFF:
            raise PlayerStatsError("完美平台 32 位 Steam ID 超出有效范围")
        return account_id + 76561197960265728
    if len(raw) == 17:
        return int(raw)
    raise PlayerStatsError("完美平台 Steam ID 必须是 10 位或 17 位数字")


def as_flag(value: Any) -> bool:
    """识别平台接口中的布尔字段。"""
    return value is True or str(value).strip().casefold() in {"1", "true", "yes"}


def image_url(value: Any, *, base_url: str = "") -> str:
    """规范化图片地址；仅在平台明确提供基础地址时补全相对路径。"""
    url = str(value or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url and not url.startswith(("http://", "https://", "data:")):
        return f"{base_url.rstrip('/')}/{url.lstrip('/')}" if base_url else ""
    return url
