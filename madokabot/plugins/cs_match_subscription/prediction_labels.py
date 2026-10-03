"""按群分配竞猜队伍编号，保留活跃编号并优先复用空位。"""

from __future__ import annotations

from typing import Any


TEAM_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def prediction_team_slots(state: dict[str, Any], group_id: str) -> list[int]:
    """读取该群的两个有效编号槽位，避免坏数据参与分配。"""
    groups = state.get("prediction_team_labels")
    entry = groups.get(group_id) if isinstance(groups, dict) else None
    if isinstance(entry, dict) and entry.get("released"):
        return []
    slots = entry.get("slots") if isinstance(entry, dict) else None
    if (
        isinstance(slots, list)
        and len(slots) == 2
        and all(type(slot) is int and slot > 0 for slot in slots)
        and slots[0] != slots[1]
    ):
        return slots.copy()
    return []


def prediction_team_labels(state: dict[str, Any], group_id: str) -> list[str]:
    """将稳定槽位显示为字母或统一的数字编号。"""
    slots = prediction_team_slots(state, group_id)
    if not slots:
        return []
    numeric = state["prediction_team_labels"][group_id].get("numeric", False)
    return [
        str(slot) if numeric or slot > len(TEAM_LETTERS) else TEAM_LETTERS[slot - 1]
        for slot in slots
    ]


def allocate_prediction_team_labels(
    data: dict[str, Any],
    enabled_groups: set[str],
) -> bool:
    """各群独立分配槽位；字母用尽后保持数字模式，直到活跃竞猜清空。"""
    by_group: dict[str, list[dict[str, Any]]] = {}
    changed = False
    for key, entry in data.items():
        if not (
            key.startswith("event:")
            and isinstance(entry, dict)
            and entry.get("kind") == "event"
            and not entry.get("completed")
        ):
            continue
        matches = entry.get("matches")
        targets = entry.get("targets")
        if not isinstance(matches, dict) or not isinstance(targets, list):
            continue
        groups = {
            str(target.get("id", ""))
            for target in targets
            if isinstance(target, dict) and target.get("kind") == "group"
        } & enabled_groups
        for state in matches.values():
            if not isinstance(state, dict):
                continue
            labels = state.get("prediction_team_labels")
            if state.get("prediction_closed") or state.get("completed"):
                # 截止标记可先于消息提交释放编号，旧快照不能再把它当作开放编号。
                if isinstance(labels, dict):
                    for label_entry in labels.values():
                        if isinstance(label_entry, dict) and not label_entry.get("released"):
                            label_entry["released"] = True
                            changed = True
                continue
            for group_id in groups:
                if (
                    isinstance(labels, dict)
                    and isinstance(labels.get(group_id), dict)
                    and labels[group_id].get("released")
                ):
                    continue
                # 尚未送达开放通知的预留槽位也占位，重试时不更换编号。
                if state.get("prediction_open") or prediction_team_slots(state, group_id):
                    by_group.setdefault(group_id, []).append(state)

    for group_id, states in by_group.items():
        used: set[int] = set()
        pending: list[dict[str, Any]] = []
        numeric = False
        for state in states:
            slots = prediction_team_slots(state, group_id)
            if slots and not used.intersection(slots):
                used.update(slots)
                numeric |= bool(state["prediction_team_labels"][group_id].get("numeric"))
            else:
                pending.append(state)
        for state in pending:
            slots = []
            slot = 1
            while len(slots) < 2:
                if slot not in used:
                    slots.append(slot)
                    used.add(slot)
                slot += 1
            groups = state.get("prediction_team_labels")
            if not isinstance(groups, dict):
                groups = {}
                state["prediction_team_labels"] = groups
            groups[group_id] = {"slots": slots, "numeric": False}
            changed = True
        numeric |= max(used, default=0) > len(TEAM_LETTERS)
        for state in states:
            entry = state["prediction_team_labels"][group_id]
            if entry.get("numeric") != numeric:
                entry["numeric"] = numeric
                changed = True
    return changed
