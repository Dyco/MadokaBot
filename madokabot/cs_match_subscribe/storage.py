"""赛事订阅的公共 JSON 持久化。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Any

from ..madoka_bundle.plugins.common.group_set import group_set
from ..madoka_bundle.plugins.common.json_data import JsonDataStore
from .config import HLTV_SUB_PATH, SUBSCRIPTIONS_PATH
from .models import (
    EVENT_STATUS_FINISHED,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_WAITING,
    EVENT_STATUSES,
    EventData,
)

_lock = asyncio.Lock()
# group_set 中保存 HLTV 赛事 ID 列表的标签名。
HLTV_SUB_GROUP_TAG = "hltv_sub"
_hltv_sub_store = JsonDataStore(HLTV_SUB_PATH, {})
_legacy_sub_store = JsonDataStore(SUBSCRIPTIONS_PATH, {})


def _read() -> dict[str, dict[str, Any]]:
    """读取赛事订阅；首次使用时迁移旧版订阅文件。"""
    _hltv_sub_store.reload()
    value = _hltv_sub_store.content
    if not isinstance(value, dict):
        value = {}
    if value:
        return value
    if not SUBSCRIPTIONS_PATH.is_file():
        return value

    _legacy_sub_store.reload()
    legacy = _legacy_sub_store.content
    if not isinstance(legacy, dict):
        return value
    if legacy:
        _hltv_sub_store.write(legacy)
    return legacy


def _write(value: dict[str, dict[str, Any]]) -> None:
    """通过通用 JSON 存储写入赛事订阅。"""
    _hltv_sub_store.write(value)


def _add_group_event_tag(target: dict[str, str], event_id: str) -> None:
    """将赛事 ID 写入群组的 HLTV 赛事推送标签。"""
    if target.get("kind") != "group" or not target.get("id"):
        return

    raw_event_ids = group_set.get(
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
    group_set.set(target["id"], HLTV_SUB_GROUP_TAG, event_ids)


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


async def subscribe(
    match_id: str,
    target: dict[str, str],
    *,
    fingerprint: str | None = None,
    completed: bool = False,
) -> bool:
    """添加订阅目标；返回本次是否新增目标。"""
    async with _lock:
        data = _read()
        key = str(match_id)
        entry = data.get(key)
        if not isinstance(entry, dict):
            entry = {
                "targets": [],
                "fingerprint": fingerprint,
                "completed": completed,
            }
            data[key] = entry
        targets = entry.get("targets")
        if not isinstance(targets, list):
            targets = []
            entry["targets"] = targets
        is_new = target not in targets
        if is_new:
            targets.append(target)
        entry["completed"] = completed
        if fingerprint is not None:
            entry["fingerprint"] = fingerprint
        _write(data)
        return is_new


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
            section = ref.get("section", "upcoming")
            if match_id not in baseline_ids:
                baseline_ids.append(match_id)
            if match_id in matches:
                if ref.get("url") and isinstance(matches[match_id], dict):
                    matches[match_id]["url"] = str(ref["url"])
                continue
            matches[match_id] = {
                "source": section,
                "url": str(ref.get("url", "")),
                "initialized": section == "result",
                "historical": section == "result",
                "started_sent": section == "result",
                "final_sent": section == "result",
                "completed": section == "result",
                "map_scores": {},
                "started_maps": [],
                "notified_maps": [],
                "rating_maps": [],
                "rating_summary_sent": False,
            }

        entry["completed"] = False
        _write(data)
        _add_group_event_tag(target, normalized_event_id)
        return is_new


async def list_active() -> dict[str, dict[str, Any]]:
    async with _lock:
        data = _read()
        return {
            match_id: entry
            for match_id, entry in data.items()
            if isinstance(entry, dict)
            and entry.get("kind") != "event"
            and not entry.get("completed", False)
        }


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

            if (
                entry.get("status") != EVENT_STATUS_FINISHED
                and not entry.get("completed", False)
            ):
                active[key.removeprefix("event:")] = entry

        if changed:
            _write(data)
        return active


async def update_state(
    match_id: str,
    *,
    fingerprint: str | None = None,
    completed: bool | None = None,
) -> None:
    async with _lock:
        data = _read()
        entry = data.get(str(match_id))
        if entry is None:
            return
        if fingerprint is not None:
            entry["fingerprint"] = fingerprint
        if completed is not None:
            entry["completed"] = completed
        _write(data)


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
