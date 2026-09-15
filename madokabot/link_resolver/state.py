"""Resolver 群级开关状态的持久化。"""

import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as store

from .constants import PLUGIN_NAME

COMMENT_MODE_MAP_NAME = "comment_mode_map.json"
RESOLVER_CONTROL_MAP_NAME = "resolver_control_map.json"

# 支持群组控制的平台标识。
RESOLVER_KEYS = (
    "bilibili",
    "douyin",
    "tiktok",
    "acfun",
    "twitter",
    "xiaohongshu",
    "youtube",
    "netease",
    "kugou",
    "weibo",
)
# 可独立控制的解析内容类型。
CONTENT_KEYS = ("image", "video", "comment")

current_resolver_key: ContextVar[str | None] = ContextVar(
    "current_resolver_key",
    default=None,
)
current_resolver_target: ContextVar[str | None] = ContextVar(
    "current_resolver_target",
    default=None,
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(default, ensure_ascii=False),
            encoding="utf-8",
        )
        return default


def load_comment_mode_map() -> dict[str, str]:
    path = store.get_data_file(PLUGIN_NAME, COMMENT_MODE_MAP_NAME)
    return dict(_read_json(path, {}))


def save_comment_mode_map(mode_map: dict[str, str]) -> None:
    path = store.get_data_file(PLUGIN_NAME, COMMENT_MODE_MAP_NAME)
    path.write_text(
        json.dumps(mode_map, ensure_ascii=False),
        encoding="utf-8",
    )


def _default_resolver_control() -> dict[str, Any]:
    """返回一个默认全部开启的 Resolver 控制状态。"""
    return {
        "resolver_enabled": True,
        "resolver_overrides": {},
        "content_enabled": {key: True for key in CONTENT_KEYS},
        "content_overrides": {},
    }


def _normalize_resolver_control_map(value: Any) -> dict[str, dict[str, Any]]:
    """清洗 Resolver 控制状态，忽略未知平台和内容类型。"""
    if not isinstance(value, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for target_id, raw_control in value.items():
        if not isinstance(raw_control, dict):
            continue

        control = _default_resolver_control()
        control["resolver_enabled"] = bool(
            raw_control.get("resolver_enabled", True)
        )

        resolver_overrides = raw_control.get("resolver_overrides", {})
        if isinstance(resolver_overrides, dict):
            control["resolver_overrides"] = {
                str(key): bool(enabled)
                for key, enabled in resolver_overrides.items()
                if str(key) in RESOLVER_KEYS
            }

        content_enabled = raw_control.get("content_enabled", {})
        if isinstance(content_enabled, dict):
            for key in CONTENT_KEYS:
                if key in content_enabled:
                    control["content_enabled"][key] = bool(content_enabled[key])

        content_overrides = raw_control.get("content_overrides", {})
        if isinstance(content_overrides, dict):
            for resolver_key, values in content_overrides.items():
                resolver_key = str(resolver_key)
                if resolver_key not in RESOLVER_KEYS or not isinstance(values, dict):
                    continue
                overrides = {
                    str(key): bool(enabled)
                    for key, enabled in values.items()
                    if str(key) in CONTENT_KEYS
                }
                if overrides:
                    control["content_overrides"][resolver_key] = overrides

        result[str(target_id)] = control
    return result


def load_resolver_control_map() -> dict[str, dict[str, Any]]:
    """加载群组 Resolver 控制状态。"""
    path = store.get_data_file(PLUGIN_NAME, RESOLVER_CONTROL_MAP_NAME)
    return _normalize_resolver_control_map(_read_json(path, {}))


def save_resolver_control_map() -> None:
    """保存群组 Resolver 控制状态。"""
    path = store.get_data_file(PLUGIN_NAME, RESOLVER_CONTROL_MAP_NAME)
    path.write_text(
        json.dumps(resolver_control_map, ensure_ascii=False),
        encoding="utf-8",
    )


resolver_control_map = load_resolver_control_map()


def _get_resolver_control(target_id: int | str | None) -> dict[str, Any] | None:
    """获取指定群组或私聊目标的 Resolver 控制状态。"""
    if target_id is None:
        return None
    return resolver_control_map.get(str(target_id))


def _ensure_resolver_control(target_id: int | str) -> dict[str, Any]:
    """创建并返回指定目标的 Resolver 控制状态。"""
    key = str(target_id)
    if key not in resolver_control_map:
        resolver_control_map[key] = _default_resolver_control()
    return resolver_control_map[key]


def is_resolver_enabled(target_id: int | str | None, resolver_key: str) -> bool:
    """判断指定目标是否允许执行某个平台解析。"""
    control = _get_resolver_control(target_id)
    if control is None:
        return True
    overrides = control["resolver_overrides"]
    if resolver_key in overrides:
        return bool(overrides[resolver_key])
    return bool(control["resolver_enabled"])


def is_content_enabled(
    target_id: int | str | None,
    resolver_key: str,
    content_key: str,
) -> bool:
    """判断指定目标是否允许发送某个平台的某类解析内容。"""
    if content_key not in CONTENT_KEYS:
        return True
    control = _get_resolver_control(target_id)
    if control is None:
        return True
    resolver_overrides = control["content_overrides"].get(resolver_key, {})
    if content_key in resolver_overrides:
        return bool(resolver_overrides[content_key])
    return bool(control["content_enabled"].get(content_key, True))


def set_all_resolvers_enabled(target_id: int | str, enabled: bool) -> None:
    """设置目标的全局解析开关，并清除平台覆盖状态。"""
    control = _ensure_resolver_control(target_id)
    control["resolver_enabled"] = enabled
    control["resolver_overrides"].clear()


def set_resolver_enabled(
    target_id: int | str,
    resolver_key: str,
    enabled: bool,
) -> None:
    """设置目标的单个平台解析开关。"""
    _ensure_resolver_control(target_id)["resolver_overrides"][resolver_key] = enabled


def set_all_content_enabled(
    target_id: int | str,
    content_key: str,
    enabled: bool,
) -> None:
    """设置目标的全局内容开关，并清除对应的平台覆盖状态。"""
    control = _ensure_resolver_control(target_id)
    control["content_enabled"][content_key] = enabled
    for overrides in control["content_overrides"].values():
        overrides.pop(content_key, None)


def set_resolver_content_enabled(
    target_id: int | str,
    resolver_key: str,
    content_key: str,
    enabled: bool,
) -> None:
    """设置目标的单个平台内容开关。"""
    control = _ensure_resolver_control(target_id)
    control["content_overrides"].setdefault(resolver_key, {})[content_key] = enabled


def split_config_list(value: str, separator: str | None = None) -> list[str]:
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]
