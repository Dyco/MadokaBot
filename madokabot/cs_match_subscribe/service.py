"""赛事订阅轮询和合并转发服务。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .assets import enrich_match_assets
from .client import HltvError, fetch_event, fetch_event_match_refs, fetch_match
from .config import config
from .models import (
    EVENT_STATUS_FINISHED,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_WAITING,
    EVENT_STATUSES,
    EventMatchRef,
    MATCH_SECTION_FINISHED,
    MATCH_SECTION_UPCOMING,
    MATCH_SECTION_WAITING,
    MapScore,
    MatchData,
    normalize_match_section,
)
from .render import render_rating_card
from .prediction import get_prediction_summary, settle_match_predictions
from .storage import (
    get_hltv_event_settings,
    list_active_events,
    update_event_state,
)

_MAP_LABELS = "一二三四五六七八九十"
_NOTIFICATION_MEMORY_TTL = 24 * 60 * 60
_notification_memory: dict[tuple[str, str], float] = {}


@dataclass(frozen=True, slots=True)
class _MatchNotification:
    """一次比赛状态变化及其可发送的消息。"""

    kind: str
    message: Message


def _cleanup_notification_memory() -> None:
    """清理短期推送幂等记忆，避免长期运行时无限增长。"""
    deadline = monotonic() - _NOTIFICATION_MEMORY_TTL
    expired = [
        key
        for key, created_at in _notification_memory.items()
        if created_at < deadline
    ]
    for key in expired:
        _notification_memory.pop(key, None)


def _notification_memory_key(match_id: str, notification: str) -> tuple[str, str]:
    return str(match_id), notification


def _notification_was_seen(match_id: str, notification: str) -> bool:
    """读取短期推送记忆。"""
    _cleanup_notification_memory()
    return _notification_memory_key(match_id, notification) in _notification_memory


def _remember_notification(match_id: str, notification: str) -> None:
    """记录已经生成过的推送事件。"""
    _cleanup_notification_memory()
    _notification_memory[_notification_memory_key(match_id, notification)] = monotonic()


def _clear_notification_memory(match_id: str) -> None:
    """清理指定比赛的短期推送记忆。"""
    match_key = str(match_id)
    for key in tuple(_notification_memory):
        if key[0] == match_key:
            _notification_memory.pop(key, None)


def _team_names(match: MatchData) -> tuple[str, str]:
    """获取比赛双方名称。"""
    first = match.teams[0].name if match.teams else "队伍A"
    second = match.teams[1].name if len(match.teams) > 1 else "队伍B"
    return first, second


def _format_score(match: MatchData, *, series: bool = False) -> str:
    """生成系列赛或地图的中文比分。"""
    first, second = _team_names(match)
    scores = " : ".join(team.score or "-" for team in match.teams[:2])
    if series:
        scores = scores.replace(" : ", ":")
    return f"{first} {scores or '-'} {second}"


def _start_message(match: MatchData, event_name: str = "") -> Message:
    """生成比赛正式开始的合并转发文本节点。"""
    first, second = _team_names(match)
    event_prefix = f"【{event_name}】" if event_name else ""
    format_code = match.format_code or "未知"
    lines = [
        f"{event_prefix}订阅赛事正式开始",
        f"{first} 对阵 {second}，赛制为 {format_code}",
    ]
    if match.format_text:
        lines.extend(("", match.format_text))
    return Message(MessageSegment.text("\n".join(lines)))


def _prediction_open_message(match: MatchData) -> Message:
    """生成开放竞猜的通知节点。"""
    first, second = _team_names(match)
    format_code = match.format_code or "未知"
    return Message(
        MessageSegment.text(
            f"【比赛编号：{match.match_id}】\n"
            f"【teamA：{first}】对阵【teamB：{second}】的{format_code}比赛现已接受竞猜。\n"
            "使用指令/cs <竞猜|预测> <A/B|队伍名> <数字>参与。\n"
            f"例如/cs 竞猜 {{{first}}} 100"
        )
    )


def _prediction_close_message(
    match: MatchData,
    summary: dict[str, Any],
) -> Message:
    """生成停止竞猜的通知节点。"""
    first, second = _team_names(match)
    teams = summary.get("teams")
    teams = teams if isinstance(teams, dict) else {}
    first_summary = teams.get(first, {})
    second_summary = teams.get(second, {})
    return Message(
        MessageSegment.text(
            f"{first}对阵{second}的比赛已开始，已停止接受预测。\n"
            f"{first}：{int(first_summary.get('count', 0))}人预测，共计"
            f"{int(first_summary.get('points', 0))}积分。\n"
            f"{second}：{int(second_summary.get('count', 0))}人预测，共计"
            f"{int(second_summary.get('points', 0))}积分。"
        )
    )


def _map_result_message(match: MatchData, result: MapScore, index: int) -> Message:
    """生成单张地图结束的合并转发文本节点。"""
    first, second = _team_names(match)
    label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
    text = (
        f"订阅赛事更新\n{first} 对阵 {second} 的图{label}结束，"
        f"比分为 {first} {result.score_display} {second}"
    )
    return Message(MessageSegment.text(text))


def _map_start_message(
    match: MatchData,
    map_name: str,
    index: int,
    event_name: str = "",
) -> Message:
    """生成单张地图开始的合并转发文本节点。"""
    first, second = _team_names(match)
    label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
    event_prefix = f"【{event_name}】" if event_name else ""
    name_suffix = f"（{map_name}）" if map_name else ""
    return Message(
        MessageSegment.text(
            f"订阅赛事更新\n"
            f"{event_prefix}\n"
            f"{first} 对阵 {second} 的图{label}{name_suffix}开始"
        )
    )


def _final_message(match: MatchData) -> Message:
    """生成系列赛结束的合并转发文本节点。"""
    return Message(
        MessageSegment.text(
            f"订阅赛事更新\n{match.display_title} 比赛结束，系列赛比分为："
            f"{_format_score(match, series=True)}"
        )
    )


async def _send_forward_to_target(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """通过 OneBot 的 forward API 发送自定义节点。"""
    kind = target.get("kind")
    target_id = target.get("id")
    if not target_id or not messages:
        return False

    sender_id = int(str(bot.self_id)) if str(bot.self_id).isdigit() else 0
    nodes = [
        MessageSegment.node_custom(sender_id, "HLTV赛事订阅", content)
        for content in messages
    ]
    if kind == "group":
        await bot.send_group_forward_msg(
            group_id=int(target_id),
            messages=nodes,
        )
        return True
    if kind == "private":
        await bot.send_private_forward_msg(
            user_id=int(target_id),
            messages=nodes,
        )
        return True
    return False


async def send_rating_forward(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """发送比赛 Rating 图片合并转发。"""
    return await _send_forward_to_target(bot, target, messages)


def _available_bots() -> Iterable[Bot]:
    """获取当前可用于推送的 OneBot V11 连接。"""
    return [bot for bot in get_bots().values() if isinstance(bot, Bot)]


async def _broadcast_forward(
    targets: list[dict[str, str]],
    messages: list[Message],
) -> bool:
    """将同一赛事更新批次作为合并转发广播。"""
    return await _broadcast_target_forwards(
        [(target, messages) for target in targets]
    )


async def _broadcast_target_forwards(
    target_messages: list[tuple[dict[str, str], list[Message]]],
) -> bool:
    """按目标分别发送赛事更新批次。

    返回值表示本批次是否至少送达一个目标。赛事状态是所有订阅目标共享的；
    如果部分目标已经成功、部分目标失败，仍必须提交状态，否则成功目标会在
    下一轮再次收到完全相同的比赛状态。
    """
    target_messages = [
        (target, messages)
        for target, messages in target_messages
        if messages
    ]
    bots = list(_available_bots())
    if not bots:
        logger.warning("没有可用 OneBot 连接，暂不推送 HLTV 赛事更新。")
        return False
    if not target_messages:
        logger.warning("HLTV 赛事订阅没有有效推送目标，暂不更新订阅状态。")
        return False

    delivered_any = False
    failed_targets: list[dict[str, str]] = []
    for target, messages in target_messages:
        delivered = False
        for bot in bots:
            try:
                if await _send_forward_to_target(bot, target, messages):
                    delivered = True
                    break
            except Exception:
                logger.exception("推送 HLTV 合并转发失败：%s", target)
        if delivered:
            delivered_any = True
        else:
            failed_targets.append(target)

    if delivered_any and failed_targets:
        logger.warning(
            "HLTV 赛事更新仅部分送达；已提交本轮状态以避免成功目标重复收取，"
            "失败目标：%s",
            failed_targets,
        )
    return delivered_any


def _current_map_scores(match: MatchData) -> dict[str, str]:
    """获取当前页面上已经产生最终比分的地图。"""
    scores: dict[str, str] = {}
    for index, result in enumerate(match.map_results):
        if result.is_finished:
            # 地图名在 HLTV 的地图切换过程中可能从占位名变成正式名称；
            # 去重状态以地图序号为准，避免同一张图被识别成两张图。
            scores[str(index)] = result.score_display
    return scores


def _map_state_seen(values: set[str], index: int) -> bool:
    """判断地图是否已经记录过，并兼容旧版的 ``序号:地图名`` 键。"""
    key = str(index)
    legacy_prefix = f"{key}:"
    return key in values or any(value.startswith(legacy_prefix) for value in values)


def _previous_map_score(
    previous_scores: dict[str, Any],
    index: int,
) -> Any:
    """读取地图上一次比分，并兼容旧版包含地图名的状态键。"""
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


def _started_map_candidates(match: MatchData) -> list[tuple[int, str]]:
    """返回由实时 Scoreboard 当前地图确认开始且尚未结束的地图。"""
    return [
        (index, result.name.strip())
        for index, result in enumerate(match.map_results)
        if result.is_started and not result.is_finished
    ]


def _parse_datetime(value: Any) -> datetime | None:
    """解析 JSON 中保存的 ISO 时间并统一为 UTC。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _prediction_due(state: dict[str, Any], now: datetime) -> bool:
    """判断比赛是否已进入标准开赛时间前30分钟。"""
    scheduled_at = _parse_datetime(state.get("scheduled_at"))
    return scheduled_at is not None and now >= scheduled_at - timedelta(minutes=30)


def _match_winner(match: MatchData) -> str:
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


def _event_status(entry: dict[str, Any]) -> str:
    """读取赛事订阅状态，并兼容旧版没有状态字段的记录。"""
    if entry.get("completed", False):
        return EVENT_STATUS_FINISHED
    status = str(entry.get("status", "")).strip()
    return status if status in EVENT_STATUSES else EVENT_STATUS_WAITING


def _event_start_at(entry: dict[str, Any]) -> datetime | None:
    """读取赛事官方开始时间，用于避免过早检查等待中的赛事。"""
    event_data = entry.get("event_data")
    if not isinstance(event_data, dict):
        return None
    return _parse_datetime(event_data.get("start_at"))


def _match_has_actual_start(match: MatchData) -> bool:
    """仅按实时 Scoreboard 当前地图判断比赛是否实际开始。"""
    return any(
        result.is_started and not result.is_finished
        for result in match.map_results
    )


def _all_matches_completed(matches: dict[str, Any]) -> bool:
    """判断赛事记录中的比赛是否全部完成。"""
    return bool(matches) and all(
        isinstance(state, dict) and state.get("completed", False)
        for state in matches.values()
    )


def _new_match_state(
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
        "final_sent": is_finished,
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
        "team_names": [],
        "format_code": "",
    }


def _historical_match_state() -> dict[str, Any]:
    """创建订阅前已经结束比赛的基线状态。"""
    state = _new_match_state(MATCH_SECTION_FINISHED)
    state.update(
        {
            "initialized": True,
            "started_sent": True,
            "final_sent": True,
            "completed": True,
        }
    )
    return state


def _match_belongs_to_event(
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


async def _rating_message(
    match: MatchData,
    cache: dict[str, MessageSegment],
    map_name: str | None = None,
) -> Message | None:
    """渲染指定统计范围的 Rating 图片节点。"""
    if map_name:
        if not match.has_map_rating(map_name):
            return None
    elif not match.has_total_rating:
        return None
    cache_key = map_name or "all"
    if cache_key not in cache:
        match = await enrich_match_assets(match)
        cache[cache_key] = await render_rating_card(match, map_name=map_name)
    return Message(cache[cache_key])


async def render_check_rating_messages(match: MatchData) -> list[Message]:
    """按比赛地图数量生成即时查询所需的 Rating 消息。"""
    if not match.has_stats or not match.rating_is_ready:
        return []

    match = await enrich_match_assets(match)
    map_names = match.rating_map_names

    if len(map_names) <= 1:
        map_name = map_names[0] if map_names else None
        return [Message(await render_rating_card(match, map_name=map_name))]

    messages: list[Message] = []
    first, second = _team_names(match)
    for index, map_name in enumerate(map_names):
        image = await render_rating_card(match, map_name=map_name)
        label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
        score = next(
            (
                result.score_display.replace(":", "-")
                for result in match.map_results
                if result.name == map_name and result.is_finished
            ),
            "-",
        )
        messages.append(
            Message(
                [
                    MessageSegment.text(
                        f"图{label}（{map_name} {first} {score} {second}）\n"
                    ),
                    image,
                ]
            )
        )

    total_image = await render_rating_card(match)
    messages.append(
        Message([MessageSegment.text("总数据\n"), total_image])
    )
    return messages


def _event_target_settings(target: dict[str, str]) -> dict[str, bool]:
    """读取赛事推送目标的设置。"""
    if target.get("kind") == "group" and target.get("id"):
        return get_hltv_event_settings(target["id"])
    return {
        "push_each_map": bool(config.hltv_subscribe_push_each_map),
        "notify_start": True,
        "prediction_enabled": False,
    }


def _messages_for_event_target(
    notifications: list[_MatchNotification],
    settings: dict[str, bool],
) -> list[Message]:
    """按群组设置筛选赛事更新消息。"""
    push_each_map = bool(settings.get("push_each_map", True))
    notify_start = bool(settings.get("notify_start", True))
    messages: list[Message] = []
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
            messages.append(notification.message)
    return messages


async def _process_event_match(
    match: MatchData,
    state: dict[str, Any],
    event_name: str,
    *,
    event_id: str,
    has_single_target: bool,
    has_prediction_target: bool,
) -> list[_MatchNotification]:
    """根据一次比赛快照生成尚未推送的节点并更新内存状态。"""
    notifications: list[_MatchNotification] = []
    initialized = bool(state.get("initialized", False))
    previous_scores = state.get("map_scores")
    if not isinstance(previous_scores, dict):
        previous_scores = {}
    notified = state.get("notified_maps")
    if not isinstance(notified, list):
        notified = []
        state["notified_maps"] = notified
    notified_set = {str(value) for value in notified}
    rating_maps = state.get("rating_maps")
    if not isinstance(rating_maps, list):
        rating_maps = []
        state["rating_maps"] = rating_maps
    rating_set = {str(value) for value in rating_maps}
    match_id = str(match.match_id)
    actual_started = _match_has_actual_start(match)
    if match.scheduled_at is not None:
        state["scheduled_at"] = match.scheduled_at.isoformat()
    state["team_names"] = [team.name for team in match.teams[:2]]
    state["format_code"] = match.format_code or "未知"
    if not initialized:
        previous_scores = _current_map_scores(match)

        # 订阅时已经结束的地图只建立基线，避免首次轮询补发历史开始通知。
        started_maps = state.get("started_maps")
        if not isinstance(started_maps, list):
            started_maps = []
            state["started_maps"] = started_maps
        started_set = {str(value) for value in started_maps}
        for index, result in enumerate(match.map_results):
            if (
                result.is_finished
                and result.is_started
                and str(index) not in started_set
            ):
                started_maps.append(str(index))
        # 订阅时已经结束的地图只建立消息和 Rating 基线，避免补发历史数据。
        for index, result in enumerate(match.map_results):
            if not result.is_finished:
                continue
            key = str(index)
            if not _map_state_seen(notified_set, index):
                notified.append(key)
                notified_set.add(key)
            if not _map_state_seen(rating_set, index):
                rating_maps.append(key)
                rating_set.add(key)

    started_maps = state.get("started_maps")
    if not isinstance(started_maps, list):
        started_maps = []
        state["started_maps"] = started_maps
    started_set = {str(value) for value in started_maps}
    for index, map_name in _started_map_candidates(match):
        key = str(index)
        if key in started_set:
            continue
        notification = f"map_start:{index}"
        if not _notification_was_seen(match_id, notification):
            notifications.append(
                _MatchNotification(
                    "map_start",
                    _map_start_message(match, map_name, index, event_name),
                )
            )
            _remember_notification(match_id, notification)
        started_maps.append(key)
        started_set.add(key)

    if actual_started and not state.get("started_sent", False):
        notification = "match_start"
        if not _notification_was_seen(match_id, notification):
            notifications.append(
                _MatchNotification("match_start", _start_message(match, event_name))
            )
            _remember_notification(match_id, notification)
        state["started_sent"] = True

    now = datetime.now(timezone.utc)
    if (
        has_prediction_target
        and not actual_started
        and not state.get("prediction_open_sent", False)
        and _prediction_due(state, now)
    ):
        notification = "prediction_open"
        if not _notification_was_seen(match_id, notification):
            notifications.append(
                _MatchNotification("prediction_open", _prediction_open_message(match))
            )
            _remember_notification(match_id, notification)
        state["prediction_open_sent"] = True
        state["prediction_open"] = True

    if (
        (actual_started or match.is_finished)
        and not state.get("prediction_closed_sent", False)
    ):
        summary = await get_prediction_summary(event_id, match_id)
        notification = "prediction_close"
        if not _notification_was_seen(match_id, notification):
            notifications.append(
                _MatchNotification(
                    "prediction_close",
                    _prediction_close_message(match, summary),
                )
            )
            _remember_notification(match_id, notification)
        state["prediction_closed_sent"] = True
        state["prediction_closed"] = True
        state["prediction_open"] = False

    rating_cache: dict[str, MessageSegment] = {}
    current_scores = _current_map_scores(match)
    for index, result in enumerate(match.map_results):
        if not result.is_finished:
            continue
        key = str(index)
        score = result.score_display
        previous_score = _previous_map_score(previous_scores, index)
        if (
            not _map_state_seen(notified_set, index)
            and previous_score != score
        ):
            notification = f"map_end:{index}"
            if not _notification_was_seen(match_id, notification):
                notifications.append(
                    _MatchNotification(
                        "map_end",
                        _map_result_message(match, result, index),
                    )
                )
                _remember_notification(match_id, notification)
            notified.append(key)
            notified_set.add(key)
        # 最后一张图同时意味着系列赛结束时，不在地图结束节点再次发送
        # 当前图 Rating；整场汇报会统一包含所有已完成地图和总 Rating。
        if (
            has_single_target
            and not match.is_finished
            and not _map_state_seen(rating_set, index)
        ):
            notification = f"map_rating:{index}"
            if _notification_was_seen(match_id, notification):
                rating_maps.append(key)
                rating_set.add(key)
            else:
                image = await _rating_message(match, rating_cache, result.name)
                if image is not None:
                    notifications.append(_MatchNotification("map_rating", image))
                    rating_maps.append(key)
                    rating_set.add(key)
                    _remember_notification(match_id, notification)

    if match.is_finished:
        if not state.get("prediction_settled", False):
            winner_name = _match_winner(match)
            if winner_name:
                settlement = await settle_match_predictions(
                    event_id,
                    match_id,
                    winner_name,
                )
                state["winner_name"] = winner_name
                state["prediction_payout"] = int(
                    settlement.get("payout_per_winner", 0)
                )
            state["prediction_settled"] = True
        if not state.get("final_sent", False):
            notification = "series_end"
            if not _notification_was_seen(match_id, notification):
                notifications.append(
                    _MatchNotification("series_end", _final_message(match))
                )
                _remember_notification(match_id, notification)
            state["final_sent"] = True
        if not state.get("rating_summary_sent", False):
            # 比赛结束和 Rating 生成不是同一时刻；没有完整 Rating 时保留
            # 赛事状态，下一次轮询继续尝试，不提前完成订阅。
            notification = "series_rating_summary"
            if _notification_was_seen(match_id, notification):
                state["rating_summary_sent"] = True
                state["completed"] = True
                state["source"] = "finished"
            else:
                rating_messages = await render_check_rating_messages(match)
                if rating_messages:
                    notifications.extend(
                        _MatchNotification("series_rating", message)
                        for message in rating_messages
                    )
                    state["rating_summary_sent"] = True
                    state["completed"] = True
                    state["source"] = "finished"
                    _remember_notification(match_id, notification)

    state["initialized"] = True
    state["map_scores"] = current_scores
    return notifications


async def _load_event_matches(
    refs: list[EventMatchRef],
) -> list[tuple[EventMatchRef, MatchData]]:
    """并发抓取赛事中需要继续跟踪的比赛详情。"""
    semaphore = asyncio.Semaphore(4)

    async def load(ref: EventMatchRef) -> tuple[EventMatchRef, MatchData] | None:
        async with semaphore:
            try:
                return ref, await fetch_match(
                    ref.match_id,
                    page_url=ref.url or None,
                )
            except HltvError as exc:
                logger.warning("轮询 HLTV 比赛 %s 失败：%s", ref.match_id, exc)
            except Exception:
                logger.exception("处理 HLTV 比赛订阅失败：%s", ref.match_id)
        return None

    results = await asyncio.gather(*(load(ref) for ref in refs))
    return [result for result in results if result is not None]


def _event_ended(entry: dict[str, Any]) -> bool:
    """判断赛事是否已经结束且所有比赛均已处理。"""
    end_at = _parse_datetime(entry.get("event_end"))
    if end_at is None:
        return False
    matches = entry.get("matches")
    return (
        isinstance(matches, dict)
        and end_at <= datetime.now(timezone.utc)
        and _all_matches_completed(matches)
    )


def _event_prediction_due(entry: dict[str, Any]) -> bool:
    """判断等待中的赛事是否已有比赛进入竞猜开放窗口。"""
    targets = [
        target
        for target in entry.get("targets", [])
        if isinstance(target, dict)
    ]
    if not any(
        _event_target_settings(target).get("prediction_enabled", False)
        for target in targets
    ):
        return False
    matches = entry.get("matches")
    if not isinstance(matches, dict):
        return False
    now = datetime.now(timezone.utc)
    return any(
        isinstance(state, dict)
        and not state.get("completed", False)
        and not state.get("prediction_closed", False)
        and (
            not state.get("scheduled_at")
            or _prediction_due(state, now)
        )
        for state in matches.values()
    )


async def _activate_waiting_event(
    event_id: str,
    entry: dict[str, Any],
) -> bool:
    """检查等待赛事是否进入进行状态。"""
    if _event_status(entry) != EVENT_STATUS_WAITING:
        return True

    now = datetime.now(timezone.utc)
    first_started_at = _parse_datetime(entry.get("first_match_started_at"))
    if first_started_at is not None:
        if first_started_at <= now:
            entry["status"] = EVENT_STATUS_ONGOING
            await update_event_state(event_id, status=EVENT_STATUS_ONGOING)
            return True
        return False

    scheduled_start = _event_start_at(entry)
    if scheduled_start is not None and scheduled_start > now:
        return False

    event = await fetch_event(event_id)
    if event.is_finished:
        entry["status"] = EVENT_STATUS_FINISHED
        entry["completed"] = True
        await update_event_state(
            event_id,
            status=EVENT_STATUS_FINISHED,
            completed=True,
        )
        return False
    status_is_live = event.event_status == "live"
    status_is_unknown_after_start = (
        event.event_status == "unknown"
        and event.start_at is not None
        and event.start_at <= now
    )
    if not (status_is_live or status_is_unknown_after_start):
        return False

    entry["status"] = EVENT_STATUS_ONGOING
    await update_event_state(event_id, status=EVENT_STATUS_ONGOING)
    return True


async def _poll_event_subscription(
    event_id: str,
    entry: dict[str, Any],
) -> None:
    """轮询一个赛事并合并发送本轮新增节点。"""
    refs = await fetch_event_match_refs(event_id)
    stored_matches = entry.get("matches")
    matches = stored_matches if isinstance(stored_matches, dict) else {}
    pending_refs: list[EventMatchRef] = []
    pending_match_ids: set[str] = set()
    max_finalization_attempts = 3

    targets = [
        target
        for target in entry.get("targets", [])
        if isinstance(target, dict)
    ]
    target_settings = [
        (target, _event_target_settings(target))
        for target in targets
    ]
    has_prediction_target = any(
        settings["prediction_enabled"]
        for _, settings in target_settings
    )

    def queue_match(ref: EventMatchRef) -> None:
        """加入本轮抓取列表并去重。"""
        if ref.match_id not in pending_match_ids:
            pending_refs.append(ref)
            pending_match_ids.add(ref.match_id)

    for ref in refs:
        section = normalize_match_section(ref.section)
        state = matches.get(ref.match_id)
        if not isinstance(state, dict):
            state = _new_match_state(section, ref.url, ref.scheduled_at)
            matches[ref.match_id] = state
            if section == MATCH_SECTION_UPCOMING or (
                has_prediction_target
                and _prediction_due(state, datetime.now(timezone.utc))
            ):
                queue_match(ref)
            continue

        if ref.url:
            # 赛事页上的链接可能在比赛开始后补全或修正 slug；每轮同步，
            # 避免继续使用旧的比赛地址。
            state["url"] = ref.url
        if ref.scheduled_at is not None:
            state["scheduled_at"] = ref.scheduled_at.isoformat()
        if state.get("completed", False):
            continue

        if section == MATCH_SECTION_UPCOMING:
            # 只有赛事页明确标记为 live 的比赛才抓取详情页。
            state["source"] = MATCH_SECTION_UPCOMING
            queue_match(ref)
            continue

        if section == MATCH_SECTION_WAITING:
            # 未开始的比赛通常只保留时间；首次启用竞猜或进入窗口时，
            # 才抓取详情页补全队伍、赛制和实时状态。
            state["source"] = MATCH_SECTION_WAITING
            if has_prediction_target and (
                not state.get("scheduled_at")
                or _prediction_due(state, datetime.now(timezone.utc))
            ):
                queue_match(ref)
            continue

        # 已跟踪的比赛从 matches 列表（live 或 waiting）移动到 Results
        # 时，允许少量一次性收尾请求，以便发送整场结束和最终 Rating；
        # 之后不再持续轮询历史比赛。新发现的 finished 比赛不会回溯抓取。
        previous_source = normalize_match_section(state.get("source"))
        attempts_raw = state.get("finalization_attempts", 0)
        try:
            attempts = max(0, int(attempts_raw))
        except (TypeError, ValueError):
            attempts = 0
        requested = bool(state.get("finalization_requested", False))
        if (
            previous_source
            in {MATCH_SECTION_UPCOMING, MATCH_SECTION_WAITING}
            or requested
        ) and attempts < max_finalization_attempts:
            state["source"] = MATCH_SECTION_FINISHED
            state["finalization_requested"] = True
            state["finalization_attempts"] = attempts + 1
            queue_match(
                EventMatchRef(
                    match_id=ref.match_id,
                    url=ref.url or str(state.get("url", "")),
                    section=MATCH_SECTION_FINISHED,
                    scheduled_at=_parse_datetime(state.get("scheduled_at")),
                )
            )
        else:
            state["source"] = MATCH_SECTION_FINISHED
            state["completed"] = True

    has_single_target = any(
        settings["push_each_map"]
        for _, settings in target_settings
    )

    loaded = await _load_event_matches(pending_refs)
    notifications: list[_MatchNotification] = []
    generated_memory_keys: set[tuple[str, str]] = set()
    event_name = str(entry.get("event_name", ""))
    observed_first_start: datetime | None = None
    for ref, match in loaded:
        if not _match_belongs_to_event(match, event_id, event_name):
            matches[ref.match_id] = _historical_match_state()
            continue
        state = matches[ref.match_id]
        if (
            observed_first_start is None
            and (_match_has_actual_start(match) or match.is_finished)
        ):
            observed_first_start = (
                _parse_datetime(match.fetched_at)
                or datetime.now(timezone.utc)
            )
        _cleanup_notification_memory()
        memory_before = set(_notification_memory)
        notifications.extend(
            await _process_event_match(
                match,
                state,
                event_name,
                event_id=event_id,
                has_single_target=has_single_target,
                has_prediction_target=has_prediction_target,
            )
        )
        generated_memory_keys.update(
            set(_notification_memory).difference(memory_before)
        )

    target_messages = [
        (
            target,
            _messages_for_event_target(notifications, settings),
        )
        for target, settings in target_settings
    ]
    target_messages = [
        (target, messages)
        for target, messages in target_messages
        if messages
    ]
    if target_messages:
        if not await _broadcast_target_forwards(target_messages):
            # 所有目标都没有确认发送成功时撤销本轮新键，下一次轮询仍可重试；
            # 已存在的键不动，避免覆盖此前已经成功发送的通知记忆。
            for key in generated_memory_keys:
                _notification_memory.pop(key, None)
            return

    first_started_at = entry.get("first_match_started_at")
    if observed_first_start is not None and not _parse_datetime(first_started_at):
        first_started_at = observed_first_start.isoformat()
        entry["first_match_started_at"] = first_started_at
        entry["status"] = EVENT_STATUS_ONGOING

    event_snapshot = {**entry, "matches": matches}
    event_finished = _event_ended(event_snapshot)
    status = EVENT_STATUS_FINISHED if event_finished else _event_status(entry)
    await update_event_state(
        event_id,
        matches=matches,
        status=status,
        first_match_started_at=(
            first_started_at if isinstance(first_started_at, str) else None
        ),
        completed=event_finished,
    )
    for match_id, state in matches.items():
        if isinstance(state, dict) and state.get("completed", False):
            _clear_notification_memory(match_id)


async def poll_subscriptions() -> None:
    """轮询赛事订阅并推送状态变化。"""
    _cleanup_notification_memory()
    entries = await list_active_events()
    for event_id, entry in entries.items():
        try:
            if _event_status(entry) == EVENT_STATUS_WAITING:
                # 没有进入竞猜窗口时，等待中的赛事不抓取比赛详情页。
                activated = await _activate_waiting_event(event_id, entry)
                if not activated and not _event_prediction_due(entry):
                    continue
            await _poll_event_subscription(event_id, entry)
        except HltvError as exc:
            logger.warning("轮询 HLTV 赛事 %s 失败：%s", event_id, exc)
        except Exception:
            logger.exception("处理 HLTV 赛事订阅失败：%s", event_id)
