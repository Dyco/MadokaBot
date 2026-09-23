"""赛事消息生成与目标通知筛选。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ..config import config
from ..models import MapScore, MatchData
from ..storage import get_hltv_event_settings

MAP_LABELS = "一二三四五六七八九十"


@dataclass(frozen=True, slots=True)
class MatchNotification:
    """一次比赛状态变化及其可发送的消息。"""

    kind: str
    message: Message


def team_names(match: MatchData) -> tuple[str, str]:
    """获取比赛双方名称。"""
    first = match.teams[0].name if match.teams else "队伍A"
    second = match.teams[1].name if len(match.teams) > 1 else "队伍B"
    return first, second


def format_score(match: MatchData, *, series: bool = False) -> str:
    """生成系列赛或地图的中文比分。"""
    first, second = team_names(match)
    scores = " : ".join(team.score or "-" for team in match.teams[:2])
    if series:
        scores = scores.replace(" : ", ":")
    return f"{first} {scores or '-'} {second}"


def start_message(match: MatchData, event_name: str = "") -> Message:
    """生成比赛正式开始的合并转发文本节点。"""
    first, second = team_names(match)
    event_prefix = f"【{event_name}】" if event_name else ""
    format_code = match.format_code or "未知"
    lines = [
        f"{event_prefix}订阅赛事正式开始",
        f"{first} 对阵 {second}，赛制为 {format_code}",
    ]
    if match.format_text:
        lines.extend(("", match.format_text))
    return Message(MessageSegment.text("\n".join(lines)))


def prediction_open_message(match: MatchData) -> Message:
    """生成开放竞猜的通知节点。"""
    first, second = team_names(match)
    format_code = match.format_code or "未知"
    return Message(
        MessageSegment.text(
            f"【比赛编号：{match.match_id}】\n"
            f"【teamA：{first}】对阵【teamB：{second}】的{format_code}比赛现已接受竞猜。\n"
            "使用指令/cs <竞猜|预测> <A/B|队伍名> <数字>参与。\n"
            f"例如/cs 竞猜 {first} 100\n"
            "【每场比赛仅可参与一次，无法修改】"
        )
    )


def prediction_close_message(
    match: MatchData,
    summary: dict[str, Any],
    *,
    refunded: bool = False,
) -> Message:
    """生成停止竞猜的通知节点。"""
    first, second = team_names(match)
    teams = summary.get("teams")
    teams = teams if isinstance(teams, dict) else {}
    first_summary = teams.get(first, {})
    second_summary = teams.get(second, {})
    lines = [
        f"{first}对阵{second}的比赛已开始，已停止接受预测。",
        f"{first}：{int(first_summary.get('count', 0))}人预测，共计"
        f"{int(first_summary.get('points', 0))}积分。",
        f"{second}：{int(second_summary.get('count', 0))}人预测，共计"
        f"{int(second_summary.get('points', 0))}积分。",
    ]
    if refunded:
        lines.append("本场竞猜因一方没有积分参与，竞猜对局失败，已退回所有下注积分。")
    return Message(MessageSegment.text("\n".join(lines)))


def map_result_message(match: MatchData, result: MapScore, index: int) -> Message:
    """生成单张地图结束的合并转发文本节点。"""
    first, second = team_names(match)
    label = MAP_LABELS[index] if index < len(MAP_LABELS) else str(index + 1)
    text = (
        f"订阅赛事更新\n{first} 对阵 {second} 的图{label}结束，"
        f"比分为 {first} {result.score_display} {second}"
    )
    return Message(MessageSegment.text(text))


def map_start_message(
    match: MatchData,
    map_name: str,
    index: int,
    event_name: str = "",
) -> Message:
    """生成单张地图开始的合并转发文本节点。"""
    first, second = team_names(match)
    label = MAP_LABELS[index] if index < len(MAP_LABELS) else str(index + 1)
    event_prefix = f"【{event_name}】" if event_name else ""
    name_suffix = f"（{map_name}）" if map_name else ""
    return Message(
        MessageSegment.text(
            f"订阅赛事更新\n"
            f"{event_prefix}\n"
            f"{first} 对阵 {second} 的图{label}{name_suffix}开始"
        )
    )


def final_message(match: MatchData) -> Message:
    """生成系列赛结束的合并转发文本节点。"""
    return Message(
        MessageSegment.text(
            f"订阅赛事更新\n{match.display_title} 比赛结束，系列赛比分为："
            f"{format_score(match, series=True)}"
        )
    )


def event_target_settings(target: dict[str, str]) -> dict[str, bool]:
    """读取赛事推送目标的设置。"""
    if target.get("kind") == "group" and target.get("id"):
        return get_hltv_event_settings(target["id"])
    return {
        "push_each_map": bool(config.hltv_subscribe_push_each_map),
        "notify_start": True,
        "prediction_enabled": False,
    }


def notifications_for_event_target(
    notifications: list[MatchNotification],
    settings: dict[str, bool],
) -> list[MatchNotification]:
    """按群组设置筛选赛事更新消息。"""
    push_each_map = bool(settings.get("push_each_map", True))
    notify_start = bool(settings.get("notify_start", True))
    selected: list[MatchNotification] = []
    for notification in notifications:
        kind = notification.kind
        if kind in {"prediction_open", "prediction_close"}:
            allowed = bool(settings.get("prediction_enabled", False))
        elif kind == "map_start":
            allowed = push_each_map and notify_start
        elif kind == "match_start":
            allowed = not push_each_map and notify_start
        elif kind in {"map_end", "map_rating"}:
            allowed = push_each_map
        else:
            allowed = kind in {"series_end", "series_rating"}
        if allowed:
            selected.append(notification)
    return selected
