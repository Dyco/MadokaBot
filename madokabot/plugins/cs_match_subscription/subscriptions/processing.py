"""单场比赛状态处理、竞猜结算和结束通知。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ..models import MATCH_SECTION_FINISHED, MatchData
from ..prediction import (
    get_prediction_summary,
    refund_uncontested_predictions,
    settle_match_predictions,
)
from ..subscriptions.memory import notification_was_seen, remember_notification
from ..subscriptions.notifications import (
    MatchNotification,
    final_message,
    map_result_message,
    map_start_message,
    prediction_close_message,
    prediction_open_message,
    start_message,
)
from ..subscriptions.rating import rating_message, render_check_rating_messages
from ..subscriptions.state import (
    current_map_scores,
    map_state_seen,
    match_has_actual_start,
    match_winner,
    prediction_due,
    previous_map_score,
    started_map_candidates,
)

MAX_RATING_RETRIES = 3


def complete_series_notifications(
    match_id: str,
    state: dict[str, Any],
    rating_messages: list[Message],
) -> list[MatchNotification]:
    """完整 Rating 到齐或重试耗尽时，完成一次系列赛结束通知。"""
    notifications = [
        MatchNotification(
            "series_end", Message(MessageSegment.text(state["rating_final_text"]))
        )
    ]
    notifications.extend(
        MatchNotification("series_rating", message) for message in rating_messages
    )
    state["rating_summary_sent"] = True
    state["rating_skipped"] = not bool(rating_messages)
    state["completed"] = True
    state["source"] = MATCH_SECTION_FINISHED
    remember_notification(match_id, "series_end")
    remember_notification(match_id, "series_rating_summary")
    if not rating_messages:
        logger.warning(
            f"HLTV 比赛 {match_id} 完整 Rating 重试 {MAX_RATING_RETRIES} 次仍不可用，"
            "仅播报比分结束"
        )
    return notifications


async def process_event_match(
    match: MatchData,
    state: dict[str, Any],
    event_name: str,
    *,
    event_id: str,
    has_single_target: bool,
    has_prediction_target: bool,
) -> list[MatchNotification]:
    """根据一次比赛快照生成尚未推送的节点并更新内存状态。"""
    notifications: list[MatchNotification] = []
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
    actual_started = match_has_actual_start(match)
    if match.scheduled_at is not None:
        state["scheduled_at"] = match.scheduled_at.isoformat()
    state["team_names"] = [team.name for team in match.teams[:2]]
    state["format_code"] = match.format_code or "未知"
    if not initialized:
        previous_scores = current_map_scores(match)

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
            if not map_state_seen(notified_set, index):
                notified.append(key)
                notified_set.add(key)
            if not map_state_seen(rating_set, index):
                rating_maps.append(key)
                rating_set.add(key)

    started_maps = state.get("started_maps")
    if not isinstance(started_maps, list):
        started_maps = []
        state["started_maps"] = started_maps
    started_set = {str(value) for value in started_maps}
    for index, map_name in started_map_candidates(match):
        key = str(index)
        if key in started_set:
            continue
        notification = f"map_start:{index}"
        if not notification_was_seen(match_id, notification):
            notifications.append(
                MatchNotification(
                    "map_start",
                    map_start_message(match, map_name, index, event_name),
                )
            )
            remember_notification(match_id, notification)
        started_maps.append(key)
        started_set.add(key)

    if actual_started and not state.get("started_sent", False):
        notification = "match_start"
        if not notification_was_seen(match_id, notification):
            notifications.append(
                MatchNotification("match_start", start_message(match, event_name))
            )
            remember_notification(match_id, notification)
        state["started_sent"] = True

    now = datetime.now(timezone.utc)
    if (
        has_prediction_target
        and not actual_started
        and not state.get("prediction_open_sent", False)
        and prediction_due(state, now)
    ):
        notification = "prediction_open"
        if not notification_was_seen(match_id, notification):
            notifications.append(
                MatchNotification("prediction_open", prediction_open_message(match))
            )
            remember_notification(match_id, notification)
        state["prediction_open_sent"] = True
        state["prediction_open"] = True

    if actual_started or match.is_finished:
        summary: dict[str, Any] | None = None
        refunded = False
        if not state.get("prediction_settled", False):
            summary = await get_prediction_summary(event_id, match_id)
            refund_result = await refund_uncontested_predictions(
                event_id,
                match_id,
                [team.name for team in match.teams[:2]],
            )
            refunded = bool(refund_result.get("refunded", False))
            if refunded:
                state["prediction_settled"] = True
                state["prediction_payout"] = 0

        if not state.get("prediction_closed_sent", False):
            if summary is None:
                summary = await get_prediction_summary(event_id, match_id)
            notification = "prediction_close"
            if not notification_was_seen(match_id, notification):
                notifications.append(
                    MatchNotification(
                        "prediction_close",
                        prediction_close_message(
                            match,
                            summary,
                            refunded=refunded,
                        ),
                    )
                )
                remember_notification(match_id, notification)
            state["prediction_closed_sent"] = True
        state["prediction_closed"] = True
        state["prediction_open"] = False

    rating_cache: dict[str, MessageSegment] = {}
    current_scores = current_map_scores(match)
    for index, result in enumerate(match.map_results):
        if not result.is_finished:
            continue
        key = str(index)
        score = result.score_display
        previous_score = previous_map_score(previous_scores, index)
        if (
            has_single_target
            and not match.is_finished
            and not map_state_seen(rating_set, index)
            and (initialized or previous_score != score)
        ):
            image = await rating_message(match, rating_cache, result.name)
            if image is None:
                # 地图比分和对应 Rating 必须同时就绪后才推送地图结束。
                continue

            notification = f"map_end:{index}"
            if not notification_was_seen(match_id, notification):
                notifications.append(
                    MatchNotification(
                        "map_end",
                        map_result_message(match, result, index),
                    )
                )
                remember_notification(match_id, notification)
            notified.append(key)
            notified_set.add(key)

            notification = f"map_rating:{index}"
            notifications.append(MatchNotification("map_rating", image))
            rating_maps.append(key)
            rating_set.add(key)
            remember_notification(match_id, notification)

    if match.is_finished:
        if not state.get("prediction_settled", False):
            winner_name = match_winner(match)
            if winner_name:
                settlement = await settle_match_predictions(
                    event_id,
                    match_id,
                    winner_name,
                )
                state["winner_name"] = winner_name
                state["prediction_payout"] = int(settlement.get("payout_per_winner", 0))
                state["prediction_settled"] = True
        if not state.get("rating_summary_sent", False):
            # 首次结束快照不计为重试，后续最多再尝试三轮。
            # 保存纯文本比分，让后续网络失败时也能完成结束播报。
            state.setdefault("rating_retry_attempts", 0)
            state["rating_final_text"] = final_message(match).extract_plain_text()
            has_map_result = any(result.is_finished for result in match.map_results)
            try:
                rating_messages = (
                    await render_check_rating_messages(match) if has_map_result else []
                )
            except Exception:
                logger.exception(f"HLTV 比赛 {match_id} 结束 Rating 渲染失败")
                rating_messages = []
            if rating_messages or state["rating_retry_attempts"] >= MAX_RATING_RETRIES:
                notifications.extend(
                    complete_series_notifications(match_id, state, rating_messages)
                )

    state["initialized"] = True
    state["map_scores"] = current_scores
    return notifications
