"""赛事订阅的公共 JSON 持久化。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from typing import Any

from madokabot.core.group.settings import group_settings
from madokabot.core.storage.json_store import JsonDataStore
from .config import HLTV_SUB_PATH, config
from .models import (
    EVENT_STATUS_FINISHED,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_WAITING,
    EVENT_STATUSES,
    EventData,
    MATCH_SECTION_FINISHED,
    normalize_match_section,
)

_lock = asyncio.Lock()
# 群设置中保存 HLTV 赛事 ID 列表的标签名。
HLTV_SUB_GROUP_TAG = "hltv_sub"
HLTV_EVENT_SETTINGS_NAME = "hltv_event_settings"
_hltv_sub_store = JsonDataStore(HLTV_SUB_PATH, {})


def _setting_bool(value: Any, default: bool) -> bool:
    """读取群配置中的布尔值，并兼容旧配置中的字符串。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def get_hltv_event_settings(group_id: str | int) -> dict[str, bool]:
    """读取群组赛事推送设置。"""
    raw_settings = group_settings.get(group_id, HLTV_EVENT_SETTINGS_NAME, {})
    if not isinstance(raw_settings, dict):
        raw_settings = {}
    return {
        "push_each_map": _setting_bool(
            raw_settings.get("push_each_map"),
            bool(config.hltv_subscribe_push_each_map),
        ),
        "notify_start": _setting_bool(
            raw_settings.get("notify_start"),
            True,
        ),
        "prediction_enabled": _setting_bool(
            raw_settings.get("prediction_enabled"),
            False,
        ),
    }


def set_hltv_event_push_each_map(
    group_id: str | int,
    push_each_map: bool,
) -> dict[str, bool]:
    """设置群组按单图或系列赛推送赛事。"""
    settings = get_hltv_event_settings(group_id)
    settings["push_each_map"] = bool(push_each_map)
    group_settings.set(group_id, HLTV_EVENT_SETTINGS_NAME, settings)
    return settings


def toggle_hltv_event_start_notification(group_id: str | int) -> bool:
    """切换群组赛事开始通知，并返回切换后的状态。"""
    settings = get_hltv_event_settings(group_id)
    settings["notify_start"] = not settings["notify_start"]
    group_settings.set(group_id, HLTV_EVENT_SETTINGS_NAME, settings)
    return settings["notify_start"]


def toggle_hltv_event_prediction(group_id: str | int) -> bool:
    """切换群组赛事竞猜，并返回切换后的状态。"""
    settings = get_hltv_event_settings(group_id)
    settings["prediction_enabled"] = not settings["prediction_enabled"]
    group_settings.set(group_id, HLTV_EVENT_SETTINGS_NAME, settings)
    return settings["prediction_enabled"]


def _read() -> dict[str, dict[str, Any]]:
    """读取赛事订阅。"""
    _hltv_sub_store.reload()
    value = _hltv_sub_store.content
    return value if isinstance(value, dict) else {}


def _write(value: dict[str, dict[str, Any]]) -> None:
    """通过通用 JSON 存储写入赛事订阅。"""
    _hltv_sub_store.write(value)


def _add_group_event_tag(target: dict[str, str], event_id: str) -> None:
    """将赛事 ID 写入群组的 HLTV 赛事推送标签。"""
    if target.get("kind") != "group" or not target.get("id"):
        return

    raw_event_ids = group_settings.get(
        target["id"],
        HLTV_SUB_GROUP_TAG,
        [],
    )
    event_ids = [
        str(value).strip()
        for value in raw_event_ids
        if str(value).strip()
    ] if isinstance(raw_event_ids, list) else []
    if event_id in event_ids:
        return
    event_ids.append(event_id)
    group_settings.set(target["id"], HLTV_SUB_GROUP_TAG, event_ids)


def _remove_group_event_tag(target: dict[str, str], event_id: str) -> None:
    """从群组的 HLTV 赛事推送标签中移除赛事 ID。"""
    if target.get("kind") != "group" or not target.get("id"):
        return

    raw_event_ids = group_settings.get(
        target["id"],
        HLTV_SUB_GROUP_TAG,
        [],
    )
    if not isinstance(raw_event_ids, list):
        return

    normalized_event_id = str(event_id).strip()
    event_ids = [
        str(value).strip()
        for value in raw_event_ids
        if str(value).strip() and str(value).strip() != normalized_event_id
    ]
    if len(event_ids) == len(raw_event_ids):
        return
    if event_ids:
        group_settings.set(target["id"], HLTV_SUB_GROUP_TAG, event_ids)
    else:
        group_settings.remove(target["id"], HLTV_SUB_GROUP_TAG)


def _remove_event_from_group_tags(event_id: str) -> None:
    """清理所有群组标签中的赛事 ID。"""
    normalized_event_id = str(event_id).strip()
    for group_id, raw_event_ids in group_settings.get_all(
        HLTV_SUB_GROUP_TAG
    ).items():
        if not isinstance(raw_event_ids, list):
            continue
        event_ids = [
            str(value).strip()
            for value in raw_event_ids
            if str(value).strip() and str(value).strip() != normalized_event_id
        ]
        if len(event_ids) == len(raw_event_ids):
            continue
        if event_ids:
            group_settings.set(group_id, HLTV_SUB_GROUP_TAG, event_ids)
        else:
            group_settings.remove(group_id, HLTV_SUB_GROUP_TAG)


def _event_name(entry: dict[str, Any], event_id: str) -> str:
    """读取赛事显示名称，缺失时回退到赛事 ID。"""
    name = str(entry.get("event_name") or "").strip()
    if not name:
        event_data = entry.get("event_data")
        if isinstance(event_data, dict):
            name = str(event_data.get("name") or "").strip()
    return name or str(event_id).strip()


def _serialize_event(event: EventData) -> dict[str, Any]:
    """将赛事数据转换为可写入 JSON 的快照。"""
    data = asdict(event)
    for key in ("start_at", "end_at"):
        value = data.get(key)
        data[key] = value.isoformat() if isinstance(value, datetime) else ""
    return data


def _event_subscription_status(event: EventData | None) -> str:
    """根据 HLTV 赛事页状态初始化赛事订阅状态。"""
    if event is not None and event.event_status == "live":
        return EVENT_STATUS_ONGOING
    return EVENT_STATUS_WAITING


def target_from_event(event: Any) -> dict[str, str] | None:
    """转换 OneBot 事件为可持久化的推送目标。"""
    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return {"kind": "group", "id": str(group_id)}
    user_id = getattr(event, "user_id", None)
    if user_id is not None:
        return {"kind": "private", "id": str(user_id)}
    return None


async def subscribe_event(
    event_id: str,
    target: dict[str, str],
    *,
    event_data: EventData | None = None,
    event_name: str = "",
    event_url: str = "",
    event_end: str = "",
    match_refs: list[dict[str, str]] | None = None,
) -> bool:
    """添加赛事订阅，并记录订阅时已经存在的比赛基线。"""
    async with _lock:
        data = _read()
        normalized_event_id = str(event_id).strip()
        key = f"event:{normalized_event_id}"
        entry = data.get(key)
        event_snapshot = _serialize_event(event_data) if event_data else None
        if not isinstance(entry, dict) or entry.get("kind") != "event":
            entry = {
                "kind": "event",
                "event_id": normalized_event_id,
                "event_data": event_snapshot or {},
                "event_name": event_name,
                "event_url": event_url,
                "event_end": event_end,
                "targets": [],
                "baseline_match_ids": [],
                "matches": {},
                "status": _event_subscription_status(event_data),
                "first_match_started_at": None,
                "completed": False,
            }
            data[key] = entry

        if event_snapshot is not None:
            entry["event_data"] = event_snapshot

        status = str(entry.get("status", "")).strip()
        if status not in EVENT_STATUSES or status == EVENT_STATUS_FINISHED:
            entry["status"] = _event_subscription_status(event_data)
        elif event_data is not None and event_data.event_status == "live":
            entry["status"] = EVENT_STATUS_ONGOING

        targets = entry.get("targets")
        if not isinstance(targets, list):
            targets = []
            entry["targets"] = targets
        is_new = target not in targets
        if is_new:
            targets.append(target)

        if event_name:
            entry["event_name"] = event_name
        if event_url:
            entry["event_url"] = event_url
        if event_end:
            entry["event_end"] = event_end

        matches = entry.get("matches")
        if not isinstance(matches, dict):
            matches = {}
            entry["matches"] = matches
        baseline_ids = entry.get("baseline_match_ids")
        if not isinstance(baseline_ids, list):
            baseline_ids = []
            entry["baseline_match_ids"] = baseline_ids

        for ref in match_refs or []:
            match_id = str(ref.get("match_id", "")).strip()
            if not match_id.isdigit():
                continue
            section = normalize_match_section(ref.get("section"))
            is_finished = section == MATCH_SECTION_FINISHED
            if match_id not in baseline_ids:
                baseline_ids.append(match_id)
            if match_id in matches:
                if isinstance(matches[match_id], dict):
                    match_state = matches[match_id]
                    if ref.get("url"):
                        match_state["url"] = str(ref["url"])
                    if ref.get("scheduled_at"):
                        match_state["scheduled_at"] = str(ref["scheduled_at"])
                    match_state.setdefault("prediction_open_sent", False)
                    match_state.setdefault("prediction_closed_sent", is_finished)
                    match_state.setdefault("prediction_open", False)
                    match_state.setdefault("prediction_closed", is_finished)
                    match_state.setdefault("prediction_settled", is_finished)
                    match_state.setdefault("winner_name", "")
                    match_state.setdefault("prediction_payout", 0)
                    match_state.setdefault("team_names", [])
                    match_state.setdefault("format_code", "")
                continue
            matches[match_id] = {
                "source": section,
                "url": str(ref.get("url", "")),
                "scheduled_at": str(ref.get("scheduled_at", "")),
                "initialized": is_finished,
                "started_sent": is_finished,
                "completed": is_finished,
                "map_scores": {},
                "started_maps": [],
                "notified_maps": [],
                "rating_maps": [],
                "rating_summary_sent": False,
                "finalization_attempts": 0,
                "prediction_open_sent": False,
                "prediction_closed_sent": is_finished,
                "prediction_open": False,
                "prediction_closed": is_finished,
                "prediction_settled": is_finished,
                "winner_name": "",
                "team_names": [],
                "format_code": "",
            }

        entry["completed"] = False
        _write(data)
        _add_group_event_tag(target, normalized_event_id)
        return is_new


async def add_event_target_if_exists(
    event_id: str,
    target: dict[str, str],
) -> tuple[bool, dict[str, Any]] | None:
    """如果本地已有赛事订阅，只追加推送目标并返回本地快照。

    返回 ``None`` 表示本地没有该赛事，调用方此时才需要访问 HLTV；
    已结束的赛事不会重新打开订阅，也不会追加推送目标。
    """
    async with _lock:
        data = _read()
        normalized_event_id = str(event_id).strip()
        entry = data.get(f"event:{normalized_event_id}")
        if not isinstance(entry, dict) or entry.get("kind") != "event":
            return None

        snapshot = deepcopy(entry)
        if (
            entry.get("completed", False)
            or str(entry.get("status", "")) == EVENT_STATUS_FINISHED
        ):
            return False, snapshot

        targets = entry.get("targets")
        if not isinstance(targets, list):
            targets = []
            entry["targets"] = targets
        is_new = target not in targets
        if is_new:
            targets.append(target)
            _write(data)

        _add_group_event_tag(target, normalized_event_id)
        return is_new, deepcopy(entry)


async def unsubscribe_event(
    event_id: str,
    target: dict[str, str],
) -> tuple[bool, str]:
    """移除当前目标对指定赛事的订阅。"""
    async with _lock:
        data = _read()
        normalized_event_id = str(event_id).strip()
        key = f"event:{normalized_event_id}"
        entry = data.get(key)
        if not isinstance(entry, dict) or entry.get("kind") != "event":
            return False, normalized_event_id

        name = _event_name(entry, normalized_event_id)
        targets = entry.get("targets")
        if not isinstance(targets, list) or target not in targets:
            return False, name

        remaining_targets = [value for value in targets if value != target]
        if remaining_targets:
            entry["targets"] = remaining_targets
        else:
            del data[key]
        _write(data)
        _remove_group_event_tag(target, normalized_event_id)
        return True, name


async def unsubscribe_all_events(target: dict[str, str]) -> int:
    """移除当前目标对全部赛事的订阅，返回实际退订数量。"""
    async with _lock:
        data = _read()
        removed = 0
        for key, entry in list(data.items()):
            if not (
                key.startswith("event:")
                and isinstance(entry, dict)
                and entry.get("kind") == "event"
            ):
                continue
            targets = entry.get("targets")
            if not isinstance(targets, list) or target not in targets:
                continue

            event_id = key.removeprefix("event:")
            remaining_targets = [value for value in targets if value != target]
            if remaining_targets:
                entry["targets"] = remaining_targets
            else:
                del data[key]
            _remove_group_event_tag(target, event_id)
            removed += 1

        if removed:
            _write(data)
        return removed


async def remove_event_subscription(event_id: str) -> tuple[bool, str]:
    """全局移除指定赛事订阅及其所有推送目标。"""
    async with _lock:
        data = _read()
        normalized_event_id = str(event_id).strip()
        key = f"event:{normalized_event_id}"
        entry = data.get(key)
        if not isinstance(entry, dict) or entry.get("kind") != "event":
            return False, normalized_event_id

        name = _event_name(entry, normalized_event_id)
        del data[key]
        _write(data)
        _remove_event_from_group_tags(normalized_event_id)
        return True, name


async def list_active_events() -> dict[str, dict[str, Any]]:
    """读取仍需轮询的赛事订阅。"""
    async with _lock:
        data = _read()
        active: dict[str, dict[str, Any]] = {}
        changed = False
        for key, entry in data.items():
            if not (
                key.startswith("event:")
                and isinstance(entry, dict)
                and entry.get("kind") == "event"
            ):
                continue

            status = str(entry.get("status", "")).strip()
            if entry.get("completed", False):
                if status != EVENT_STATUS_FINISHED:
                    entry["status"] = EVENT_STATUS_FINISHED
                    changed = True
            elif status not in EVENT_STATUSES:
                entry["status"] = EVENT_STATUS_WAITING
                changed = True
            if "first_match_started_at" not in entry:
                entry["first_match_started_at"] = None
                changed = True
            if "matches" not in entry or not isinstance(entry.get("matches"), dict):
                entry["matches"] = {}
                changed = True

            if (
                entry.get("status") != EVENT_STATUS_FINISHED
                and not entry.get("completed", False)
            ):
                active[key.removeprefix("event:")] = entry

        if changed:
            _write(data)
        return active


async def update_event_state(
    event_id: str,
    *,
    matches: dict[str, Any] | None = None,
    status: str | None = None,
    first_match_started_at: str | None = None,
    completed: bool | None = None,
) -> None:
    """保存赛事订阅的比赛状态。"""
    async with _lock:
        data = _read()
        entry = data.get(f"event:{event_id}")
        if not isinstance(entry, dict) or entry.get("kind") != "event":
            return
        if matches is not None:
            entry["matches"] = matches
        if status in EVENT_STATUSES:
            entry["status"] = status
        if first_match_started_at is not None:
            entry["first_match_started_at"] = first_match_started_at
        if completed is not None:
            entry["completed"] = completed
            if completed:
                entry["status"] = EVENT_STATUS_FINISHED
        _write(data)


def _target_in_entry(entry: dict[str, Any], target: dict[str, str]) -> bool:
    """判断赛事订阅是否包含指定推送目标。"""
    targets = entry.get("targets")
    return isinstance(targets, list) and target in targets


async def list_open_prediction_matches(group_id: str | int) -> list[dict[str, Any]]:
    """读取当前群正在接受竞猜的比赛。"""
    normalized_group_id = str(group_id).strip()
    if not get_hltv_event_settings(normalized_group_id)["prediction_enabled"]:
        return []

    target = {"kind": "group", "id": normalized_group_id}
    async with _lock:
        data = _read()
        matches: list[dict[str, Any]] = []
        for key, entry in data.items():
            if not (
                key.startswith("event:")
                and isinstance(entry, dict)
                and entry.get("kind") == "event"
                and _target_in_entry(entry, target)
            ):
                continue
            event_id = key.removeprefix("event:")
            raw_matches = entry.get("matches")
            if not isinstance(raw_matches, dict):
                continue
            for match_id, state in raw_matches.items():
                if not isinstance(state, dict):
                    continue
                if not state.get("prediction_open") or state.get("prediction_closed"):
                    continue
                matches.append(
                    {
                        "event_id": event_id,
                        "match_id": str(match_id),
                        "event_name": _event_name(entry, event_id),
                        "team_names": list(state.get("team_names") or []),
                        "format_code": str(state.get("format_code") or "未知"),
                        "scheduled_at": str(state.get("scheduled_at") or ""),
                    }
                )
        return matches


async def get_prediction_match_context(
    group_id: str | int,
    match_id: str,
) -> dict[str, Any] | None:
    """读取指定群可查看的赛事竞猜状态。"""
    target = {"kind": "group", "id": str(group_id).strip()}
    normalized_match_id = str(match_id).strip()
    async with _lock:
        data = _read()
        for key, entry in data.items():
            if not (
                key.startswith("event:")
                and isinstance(entry, dict)
                and entry.get("kind") == "event"
                and _target_in_entry(entry, target)
            ):
                continue
            matches = entry.get("matches")
            if not isinstance(matches, dict):
                continue
            state = matches.get(normalized_match_id)
            if not isinstance(state, dict):
                continue
            return {
                "event_id": key.removeprefix("event:"),
                "event_name": _event_name(entry, key.removeprefix("event:")),
                "state": deepcopy(state),
            }
    return None
