"""赛事订阅的轻量 JSON 持久化。"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .config import SUBSCRIPTIONS_PATH

_lock = asyncio.Lock()


def _read() -> dict[str, dict[str, Any]]:
    if not SUBSCRIPTIONS_PATH.is_file():
        return {}
    try:
        value = json.loads(SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(value: dict[str, dict[str, Any]]) -> None:
    SUBSCRIPTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="subscriptions-",
        suffix=".json",
        dir=str(SUBSCRIPTIONS_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
        Path(temp_name).replace(SUBSCRIPTIONS_PATH)
    finally:
        temp_path = Path(temp_name)
        if temp_path.exists():
            temp_path.unlink()


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
    event_name: str = "",
    event_url: str = "",
    event_end: str = "",
    match_refs: list[dict[str, str]] | None = None,
) -> bool:
    """添加赛事订阅，并记录订阅时已经存在的比赛基线。"""
    async with _lock:
        data = _read()
        key = f"event:{event_id}"
        entry = data.get(key)
        if not isinstance(entry, dict) or entry.get("kind") != "event":
            entry = {
                "kind": "event",
                "event_id": str(event_id),
                "event_name": event_name,
                "event_url": event_url,
                "event_end": event_end,
                "targets": [],
                "baseline_match_ids": [],
                "matches": {},
                "completed": False,
            }
            data[key] = entry

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
                continue
            matches[match_id] = {
                "source": section,
                "initialized": section == "result",
                "historical": section == "result",
                "started_sent": section == "result",
                "final_sent": section == "result",
                "completed": section == "result",
                "map_scores": {},
                "notified_maps": [],
            }

        entry["completed"] = False
        _write(data)
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
        return {
            key.removeprefix("event:"): entry
            for key, entry in data.items()
            if key.startswith("event:")
            and isinstance(entry, dict)
            and entry.get("kind") == "event"
            and not entry.get("completed", False)
        }


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
        if completed is not None:
            entry["completed"] = completed
        _write(data)
