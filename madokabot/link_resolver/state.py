"""Resolver 群级开关状态的持久化。"""

import json
from pathlib import Path
from typing import Any

import nonebot_plugin_localstore as store

from .constants import PLUGIN_NAME, RESOLVE_SHUTDOWN_LIST_NAME

COMMENT_SHUTDOWN_LIST_NAME = "comment_shutdown_list.json"
COMMENT_MODE_MAP_NAME = "comment_mode_map.json"


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


def load_resolver_shutdown_list() -> list[Any]:
    path = store.get_data_file(PLUGIN_NAME, RESOLVE_SHUTDOWN_LIST_NAME)
    return list(_read_json(path, []))


def save_resolver_shutdown_list(group_ids: list[Any]) -> None:
    path = store.get_data_file(PLUGIN_NAME, RESOLVE_SHUTDOWN_LIST_NAME)
    path.write_text(
        json.dumps(group_ids, ensure_ascii=False),
        encoding="utf-8",
    )


def load_comment_shutdown_list() -> list[Any]:
    path = store.get_data_file(PLUGIN_NAME, COMMENT_SHUTDOWN_LIST_NAME)
    return list(_read_json(path, []))


def save_comment_shutdown_list(group_ids: list[Any]) -> None:
    path = store.get_data_file(PLUGIN_NAME, COMMENT_SHUTDOWN_LIST_NAME)
    path.write_text(
        json.dumps(group_ids, ensure_ascii=False),
        encoding="utf-8",
    )


def load_comment_mode_map() -> dict[str, str]:
    path = store.get_data_file(PLUGIN_NAME, COMMENT_MODE_MAP_NAME)
    return dict(_read_json(path, {}))


def save_comment_mode_map(mode_map: dict[str, str]) -> None:
    path = store.get_data_file(PLUGIN_NAME, COMMENT_MODE_MAP_NAME)
    path.write_text(
        json.dumps(mode_map, ensure_ascii=False),
        encoding="utf-8",
    )


def split_config_list(value: str, separator: str | None = None) -> list[str]:
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]
