"""比赛和赛事状态的构建与判断。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import config
from ..models import (
    EVENT_STATUS_FINISHED,
    EVENT_STATUS_WAITING,
    EVENT_STATUSES,
    MATCH_SECTION_FINISHED,
    MatchData,
    normalize_match_section,
)


def current_map_scores(match: MatchData) -> dict[str, str]:
    """获取当前页面上已经产生最终比分的地图。"""
    scores: dict[str, str] = {}
    for index, result in enumerate(match.map_results):
        if result.is_finished:
            scores[str(index)] = result.score_display
    return scores


def map_state_seen(values: set[str], index: int) -> bool:
    """地图状态去重检查方法。"""
    key = str(index)
    legacy_prefix = f"{key}:"
    return key in values or any(value.startswith(legacy_prefix) for value in values)


def previous_map_score(
    previous_scores: dict[str, Any],
    index: int,
) -> Any:
    """上次地图比分读取方法。"""
    key = str(index)
    if key in previous_scores:
        return previous_scores[key]
    legacy_prefix = f"{key}:"
    return next(
        (
            value
            for raw_key, value in previous_scores.items()
            if str(raw_key).startswith(legacy_prefix)
        ),
        None,
    )


def started_map_candidates(match: MatchData) -> list[tuple[int, str]]:
    """进行中地图查询方法。"""
    if match.is_finished:
        return []
    return [
        (index, result.name.strip())
        for index, result in enumerate(match.map_results)
        if result.is_started and not result.is_finished
    ]


def parse_datetime(value: Any) -> datetime | None:
    """UTC时间解析方法。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def prediction_due(state: dict[str, Any], now: datetime) -> bool:
    """判断比赛是否已进入标准开赛时间前30分钟。"""
    scheduled_at = parse_datetime(state.get("scheduled_at"))
    return scheduled_at is not None and now >= scheduled_at - timedelta(minutes=30)


def match_winner(match: MatchData) -> str:
    """按系列赛比分读取获胜队伍。"""
    if len(match.teams) < 2:
        return ""
    scores: list[int] = []
    for team in match.teams[:2]:
        try:
            scores.append(int(str(team.score or "").strip()))
        except ValueError:
            scores = []
            break
    if len(scores) == 2 and scores[0] != scores[1]:
        return match.teams[0].name if scores[0] > scores[1] else match.teams[1].name

    map_wins = [0, 0]
    for result in match.map_results:
        try:
            first_score = int(str(result.team1_score or "").strip())
            second_score = int(str(result.team2_score or "").strip())
        except ValueError:
            continue
        if first_score > second_score:
            map_wins[0] += 1
        elif second_score > first_score:
            map_wins[1] += 1
    if map_wins[0] != map_wins[1] and any(map_wins):
        return match.teams[0].name if map_wins[0] > map_wins[1] else match.teams[1].name
    return ""


def event_status(entry: dict[str, Any]) -> str:
    """读取赛事订阅状态。"""
    if entry.get("completed", False):
        return EVENT_STATUS_FINISHED
    status = str(entry.get("status", "")).strip()
    return status if status in EVENT_STATUSES else EVENT_STATUS_WAITING


def event_start_at(entry: dict[str, Any]) -> datetime | None:
    """赛事开始时间读取方法。"""
    event_data = entry.get("event_data")
    if not isinstance(event_data, dict):
        return None
    return parse_datetime(event_data.get("start_at"))


def match_has_actual_start(match: MatchData) -> bool:
    """比赛实际开始检查方法。"""
    return any(
        result.is_started and not result.is_finished for result in match.map_results
    )


def all_matches_completed(matches: dict[str, Any]) -> bool:
    """判断赛事记录中的比赛是否全部完成。"""
    return bool(matches) and all(
        isinstance(state, dict) and state.get("completed", False)
        for state in matches.values()
    )


def new_match_state(
    section: str,
    page_url: str = "",
    scheduled_at: datetime | None = None,
) -> dict[str, Any]:
    """创建一场新发现比赛的轮询状态。"""
    normalized_section = normalize_match_section(section)
    is_finished = normalized_section == MATCH_SECTION_FINISHED
    return {
        "source": normalized_section,
        "url": page_url,
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else "",
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
        "prediction_payout": 0,
        "prediction_public_pool": int(config.cs_prediction_public_pool),
        "team_names": [],
        "format_code": "",
    }


def historical_match_state() -> dict[str, Any]:
    """创建订阅前已经结束比赛的基线状态。"""
    state = new_match_state(MATCH_SECTION_FINISHED)
    state.update(
        {
            "initialized": True,
            "started_sent": True,
            "completed": True,
        }
    )
    return state


def match_belongs_to_event(
    match: MatchData,
    event_id: str,
    event_name: str,
) -> bool:
    """过滤赛事列表页侧栏混入的其他比赛。"""
    if match.event_url and f"/events/{event_id}" not in match.event_url:
        return False
    if not match.event_url and event_name and match.event_name:
        return match.event_name == event_name
    return True


def event_ended(entry: dict[str, Any]) -> bool:
    """判断赛事是否已经结束且所有比赛均已处理。"""
    end_at = parse_datetime(entry.get("event_end"))
    if end_at is None:
        return False
    matches = entry.get("matches")
    return (
        isinstance(matches, dict)
        and end_at <= datetime.now(timezone.utc)
        and all_matches_completed(matches)
    )
