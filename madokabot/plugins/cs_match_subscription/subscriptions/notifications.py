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
    match_id: str = ""
    event_id: str = ""


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


def prediction_open_message(
    match: MatchData,
    *,
    public_pool: int = 0,
    team_labels: list[str] | None = None,
) -> Message:
    """生成精简开放竞猜节点。"""
    first, second = team_names(match)
    labels = team_labels or ["A", "B"]
    format_code = match.format_code or "未知"
    return Message(
        MessageSegment.text(
            f"【已开放竞猜，{first}对阵{second}，{format_code}，编号{match.match_id}】\n"
            "发送/cs <竞猜|预测> <竞猜编号|队伍名> <积分>参与\n"
            f"team{labels[0]}：{first}\n"
            f"team{labels[1]}：{second}\n"
            f"如/cs 竞猜 team{labels[0]} 100\n\n"
            "【每场比赛仅可参与一次，无法修改！】"
        )
    )


def prediction_notifications_with_labels(
    notifications: list[MatchNotification],
    candidates: list[dict[str, Any]],
    matches: dict[str, MatchData],
    states: dict[str, Any],
) -> list[MatchNotification]:
    """竞猜开放通知生成方法。"""
    if not any(item.kind == "prediction_open" for item in notifications):
        return notifications
    by_match = {candidate["match_id"]: candidate for candidate in candidates}
    selected = []
    for item in notifications:
        if item.kind != "prediction_open":
            selected.append(item)
            continue
        labels = by_match.get(item.match_id, {}).get("team_labels") or []
        if len(labels) != 2:
            raise ValueError(f"开放竞猜缺少群编号：{item.match_id}")
        selected.append(MatchNotification(
            "prediction_open",
            prediction_open_message(
                matches[item.match_id],
                public_pool=int(states[item.match_id]["prediction_public_pool"]),
                team_labels=labels,
            ),
            item.match_id,
        ))
    if len(candidates) > 1:
        lines = ["当前可下注竞猜"]
        for index, candidate in enumerate(candidates, start=1):
            first, second = candidate["team_names"][:2]
            labels = candidate["team_labels"]
            lines.append(
                f"{index}.{first}(team{labels[0]}) 对阵 {second}(team{labels[1]})"
            )
        selected.append(MatchNotification(
            "prediction_open", Message(MessageSegment.text("\n".join(lines)))
        ))
    return selected


def prediction_close_message(
    match: MatchData,
    summary: dict[str, Any],
    *,
    refunded: bool = False,
    public_pool: int = 0,
) -> Message:
    """竞猜截止通知生成方法。"""
    first, second = team_names(match)
    teams = summary.get("teams")
    teams = teams if isinstance(teams, dict) else {}
    first_summary = teams.get(first, {})
    second_summary = teams.get(second, {})
    lines = [
        f"比赛已开始（{first} VS {second} 编号{match.match_id}），竞猜已截止。",
        f"{first}：{int(first_summary.get('count', 0))}人预测，共计"
        f"{int(first_summary.get('points', 0))}积分。",
        f"{second}：{int(second_summary.get('count', 0))}人预测，共计"
        f"{int(second_summary.get('points', 0))}积分。",
        f"系统公池：{public_pool}积分。",
    ]
    if refunded:
        lines.append("本场竞猜因一方没有积分参与，竞猜对局失败，已退回所有下注积分。")
    return Message(MessageSegment.text("\n".join(lines)))


def prediction_settlement_message(report: dict[str, Any]) -> Message:
    """竞猜结算通知生成方法。"""
    if report["winner_name"]:
        other_points = report["opponent_points"]
        other_count = report["opponent_count"]
        count_text = f"（{other_count}人）" if other_count else ""
        lines = [
            f"【{report['winner_name']}获胜】竞猜结算",
            f"系统公池：{report['public_pool']}积分",
            f"其他下注：{other_points}积分{count_text}",
        ]
    else:
        lines = ["【竞猜退款】竞猜结算", "本场仅退回下注本金"]
    for player in report["players"]:
        lines.append(f"{player['name']}：{player['net_points']:+d}积分")
    return Message(MessageSegment.text("\n".join(lines)))


def map_result_message(match: MatchData, result: MapScore, index: int) -> Message:
    """地图结束消息生成方法。"""
    first, second = team_names(match)
    label = MAP_LABELS[index] if index < len(MAP_LABELS) else str(index + 1)
    winner = ""
    try:
        first_score = int(result.team1_score)
        second_score = int(result.team2_score)
    except (TypeError, ValueError):
        pass
    else:
        if first_score != second_score:
            winner = first if first_score > second_score else second
    winner_text = f"，{winner}获胜" if winner else ""
    text = (
        f"图{label}结束{winner_text}\n"
        f"比分为{first} {result.score_display} {second}"
    )
    return Message(MessageSegment.text(text))


def map_start_message(
    match: MatchData,
    map_name: str,
    index: int,
    event_name: str = "",
) -> Message:
    """地图开始消息生成方法。"""
    first, second = team_names(match)
    label = MAP_LABELS[index] if index < len(MAP_LABELS) else str(index + 1)
    lines = [
        f"{first}对阵{second}的比赛已开始",
        f"图{label}：{map_name}" if map_name else f"图{label}",
    ]
    if event_name:
        lines.append(f"【{event_name}】")
    return Message(MessageSegment.text("\n".join(lines)))


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
