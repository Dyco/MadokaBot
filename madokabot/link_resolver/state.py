"""Resolver 群级开关状态的统一持久化。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from ..madoka_bundle.plugins.common.group_set import group_set
from .constants import PLUGIN_NAME

LINK_RESOLVER_DATA_NAME = PLUGIN_NAME
COMMENT_MODE_KEY = "comment_mode"
RESOLVER_CONTROL_KEY = "resolver_control"

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


def _normalize_comment_mode_map(value: Any) -> dict[str, str]:
    """清洗评论模式，仅保留有效的群组和模式。"""
    if not isinstance(value, dict):
        return {}
    return {
        str(target_id): mode
        for target_id, mode in value.items()
        if mode in {"image", "text"}
    }


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


def _load_group_state() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """从群组配置 JSON 读取 Resolver 状态。"""
    comment_modes: dict[str, str] = {}
    control_map: dict[str, dict[str, Any]] = {}

    for target_id, raw_data in group_set.get_all(LINK_RESOLVER_DATA_NAME).items():
        if not isinstance(raw_data, dict):
            continue

        mode = raw_data.get(COMMENT_MODE_KEY)
        if mode in {"image", "text"}:
            comment_modes[str(target_id)] = mode

        raw_control = raw_data.get(RESOLVER_CONTROL_KEY)
        control_map.update(
            _normalize_resolver_control_map({str(target_id): raw_control})
        )
    return comment_modes, control_map


def _save_group_state(
    comment_modes: dict[str, str],
    control_map: dict[str, dict[str, Any]],
) -> None:
    """将 Resolver 状态合并写入群组配置 JSON。"""
    target_ids = set(comment_modes) | set(control_map)
    for target_id in target_ids:
        raw_data = group_set.get(target_id, LINK_RESOLVER_DATA_NAME, {})
        data = dict(raw_data) if isinstance(raw_data, dict) else {}
        if target_id in comment_modes:
            data[COMMENT_MODE_KEY] = comment_modes[target_id]
        if target_id in control_map:
            data[RESOLVER_CONTROL_KEY] = control_map[target_id]
        group_set.set(target_id, LINK_RESOLVER_DATA_NAME, data)


def load_comment_mode_map() -> dict[str, str]:
    """加载群组评论模式。"""
    return _load_group_state()[0]


def save_comment_mode_map(mode_map: dict[str, str]) -> None:
    """保存群组评论模式到群组配置 JSON。"""
    normalized_map = _normalize_comment_mode_map(mode_map)
    comment_mode_map.clear()
    comment_mode_map.update(normalized_map)
    _, control_map = _load_group_state()
    _save_group_state(normalized_map, control_map)


def load_resolver_control_map() -> dict[str, dict[str, Any]]:
    """加载群组 Resolver 控制状态。"""
    return _load_group_state()[1]


def save_resolver_control_map() -> None:
    """保存群组 Resolver 控制状态到群组配置 JSON。"""
    normalized_map = _normalize_resolver_control_map(resolver_control_map)
    resolver_control_map.clear()
    resolver_control_map.update(normalized_map)
    comment_modes, _ = _load_group_state()
    _save_group_state(comment_modes, normalized_map)


comment_mode_map, resolver_control_map = _load_group_state()


def _get_resolver_control(target_id: int | str | None) -> dict[str, Any] | None:
    """获取指定群组的 Resolver 控制状态。"""
    if target_id is None:
        return None
    return resolver_control_map.get(str(target_id))


def _ensure_resolver_control(target_id: int | str) -> dict[str, Any]:
    """创建并返回指定群组的 Resolver 控制状态。"""
    key = str(target_id)
    if key not in resolver_control_map:
        resolver_control_map[key] = _default_resolver_control()
    return resolver_control_map[key]


def is_resolver_enabled(target_id: int | str | None, resolver_key: str) -> bool:
    """判断指定群组是否允许执行某个平台解析。"""
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
    """判断指定群组是否允许发送某个平台的某类解析内容。"""
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
    """设置群组的全局解析开关，并清除平台覆盖状态。"""
    control = _ensure_resolver_control(target_id)
    control["resolver_enabled"] = enabled
    control["resolver_overrides"].clear()


def set_resolver_enabled(
    target_id: int | str,
    resolver_key: str,
    enabled: bool,
) -> None:
    """设置群组的单个平台解析开关。"""
    _ensure_resolver_control(target_id)["resolver_overrides"][resolver_key] = enabled


def set_all_content_enabled(
    target_id: int | str,
    content_key: str,
    enabled: bool,
) -> None:
    """设置群组的全局内容开关，并清除对应的平台覆盖状态。"""
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
    """设置群组的单个平台内容开关。"""
    control = _ensure_resolver_control(target_id)
    control["content_overrides"].setdefault(resolver_key, {})[content_key] = enabled


def split_config_list(value: str, separator: str | None = None) -> list[str]:
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]
