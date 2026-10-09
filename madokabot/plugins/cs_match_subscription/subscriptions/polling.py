"""赛事激活、比赛抓取、通知发送与状态提交。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from nonebot import logger

from ..client import HltvError, fetch_event, fetch_event_match_refs, fetch_match
from ..models import (
    EVENT_STATUS_FINISHED,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_WAITING,
    MATCH_SECTION_FINISHED,
    MATCH_SECTION_UPCOMING,
    MATCH_SECTION_WAITING,
    EventMatchRef,
    MatchData,
    normalize_match_section,
)
from ..storage import list_active_events, reserve_prediction_team_labels, update_event_state
from ..subscriptions.delivery import broadcast_target_notifications
from ..subscriptions.memory import (
    cleanup_notification_memory,
    clear_notification_memory,
    notification_memory,
)
from ..subscriptions.notifications import (
    MatchNotification,
    event_target_settings,
    notifications_for_event_target,
    prediction_notifications_with_labels,
)
from ..subscriptions.processing import (
    MAX_RATING_RETRIES,
    complete_series_notifications,
    process_event_match,
)
from ..subscriptions.settlement import (
    reconcile_unsettled_predictions,
    with_prediction_settlement_notifications,
)
from ..subscriptions.state import (
    event_ended,
    event_start_at,
    event_status,
    historical_match_state,
    match_belongs_to_event,
    match_has_actual_start,
    new_match_state,
    parse_datetime,
    prediction_due,
)


async def load_event_matches(
    refs: list[EventMatchRef],
) -> list[tuple[EventMatchRef, MatchData]]:
    """并发抓取赛事中需要继续跟踪的比赛详情。"""
    semaphore = asyncio.Semaphore(4)

    async def load(ref: EventMatchRef) -> tuple[EventMatchRef, MatchData] | None:
        """在并发限制内读取单场比赛。"""
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


def event_prediction_due(entry: dict[str, Any]) -> bool:
    """判断等待中的赛事是否已有比赛进入竞猜开放窗口。"""
    targets = [
        target for target in entry.get("targets", []) if isinstance(target, dict)
    ]
    if not any(
        event_target_settings(target).get("prediction_enabled", False)
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
        and (not state.get("scheduled_at") or prediction_due(state, now))
        for state in matches.values()
    )


async def activate_waiting_event(
    event_id: str,
    entry: dict[str, Any],
) -> bool:
    """检查等待赛事是否进入进行状态。"""
    if event_status(entry) != EVENT_STATUS_WAITING:
        return True

    now = datetime.now(timezone.utc)
    first_started_at = parse_datetime(entry.get("first_match_started_at"))
    if first_started_at is not None:
        if first_started_at <= now:
            entry["status"] = EVENT_STATUS_ONGOING
            await update_event_state(event_id, status=EVENT_STATUS_ONGOING)
            return True
        return False

    scheduled_start = event_start_at(entry)
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


async def poll_event_subscription(
    event_id: str,
    entry: dict[str, Any],
) -> None:
    """轮询一个赛事并合并发送本轮新增节点。"""
    refs = await fetch_event_match_refs(event_id)
    stored_matches = entry.get("matches")
    matches = stored_matches if isinstance(stored_matches, dict) else {}
    pending_refs: list[EventMatchRef] = []
    pending_match_ids: set[str] = set()

    targets = [
        target for target in entry.get("targets", []) if isinstance(target, dict)
    ]
    target_settings = [(target, event_target_settings(target)) for target in targets]
    has_prediction_target = any(
        settings["prediction_enabled"] for _, settings in target_settings
    )

    def queue_match(ref: EventMatchRef) -> None:
        """按比赛编号去重并加入本轮抓取队列。"""
        """加入本轮抓取列表并去重。"""
        if ref.match_id not in pending_match_ids:
            pending_refs.append(ref)
            pending_match_ids.add(ref.match_id)

    for ref in refs:
        section = normalize_match_section(ref.section)
        state = matches.get(ref.match_id)
        if not isinstance(state, dict):
            state = new_match_state(section, ref.url, ref.scheduled_at)
            matches[ref.match_id] = state
            if section == MATCH_SECTION_UPCOMING or (
                has_prediction_target
                and prediction_due(state, datetime.now(timezone.utc))
            ):
                queue_match(ref)
            continue

        if ref.url:
            # 赛事页可能补全slug，每轮需同步比赛地址。
            state["url"] = ref.url
        if ref.scheduled_at is not None:
            state["scheduled_at"] = ref.scheduled_at.isoformat()
        if state.get("completed", False):
            continue

        if section == MATCH_SECTION_UPCOMING:
            state["source"] = MATCH_SECTION_UPCOMING
            queue_match(ref)
            continue

        if section == MATCH_SECTION_WAITING:
            # 等待中的比赛仅在竞猜需要详情时抓取。
            state["source"] = MATCH_SECTION_WAITING
            if has_prediction_target and (
                not state.get("scheduled_at")
                or prediction_due(state, datetime.now(timezone.utc))
            ):
                queue_match(ref)
            continue

        # 跟踪比赛移入Results后有限重试，不回溯新发现的已结束比赛。
        previous_source = normalize_match_section(state.get("source"))
        attempts_raw = state.get("finalization_attempts", 0)
        try:
            attempts = max(0, int(attempts_raw))
        except (TypeError, ValueError):
            attempts = 0
        requested = bool(state.get("finalization_requested", False))
        if (
            previous_source
            in {
                MATCH_SECTION_UPCOMING,
                MATCH_SECTION_WAITING,
                MATCH_SECTION_FINISHED,
            }
            or requested
        ):
            state["source"] = MATCH_SECTION_FINISHED
            state["finalization_requested"] = True
            state["finalization_attempts"] = attempts + 1
            queue_match(
                EventMatchRef(
                    match_id=ref.match_id,
                    url=ref.url or str(state.get("url", "")),
                    section=MATCH_SECTION_FINISHED,
                    scheduled_at=parse_datetime(state.get("scheduled_at")),
                )
            )
        else:
            state["source"] = MATCH_SECTION_FINISHED
            state["completed"] = True

    # 比赛从列表消失后仍需完成结束通知的有限重试。
    for match_id, state in matches.items():
        if (
            isinstance(state, dict)
            and state.get("rating_final_text")
            and not state.get("completed", False)
        ):
            queue_match(
                EventMatchRef(
                    match_id=str(match_id),
                    url=str(state.get("url", "")),
                    section=MATCH_SECTION_FINISHED,
                )
            )

    for ref in pending_refs:
        state = matches[ref.match_id]
        if state.get("rating_final_text") and not state.get(
            "rating_summary_sent", False
        ):
            state["rating_retry_attempts"] = min(
                int(state.get("rating_retry_attempts", 0)) + 1,
                MAX_RATING_RETRIES,
            )

    has_single_target = any(
        settings["push_each_map"] for _, settings in target_settings
    )

    loaded = await load_event_matches(pending_refs)
    notifications: list[MatchNotification] = []
    generated_memory_keys: set[tuple[str, str]] = set()
    event_name = str(entry.get("event_name", ""))
    observed_first_start: datetime | None = None
    for ref, match in loaded:
        if not match_belongs_to_event(match, event_id, event_name):
            matches[ref.match_id] = historical_match_state()
            continue
        state = matches[ref.match_id]
        if observed_first_start is None and (
            match_has_actual_start(match) or match.is_finished
        ):
            observed_first_start = parse_datetime(match.fetched_at) or datetime.now(
                timezone.utc
            )
        cleanup_notification_memory()
        memory_before = set(notification_memory)
        notifications.extend(
            await process_event_match(
                match,
                state,
                event_name,
                event_id=event_id,
                has_single_target=has_single_target,
                has_prediction_target=has_prediction_target,
            )
        )
        generated_memory_keys.update(set(notification_memory).difference(memory_before))

    # 最终抓取失败时用已保存的结束比分收尾。
    for ref in pending_refs:
        state = matches[ref.match_id]
        if (
            state.get("rating_final_text")
            and not state.get("completed", False)
            and state.get("rating_retry_attempts", 0) >= MAX_RATING_RETRIES
        ):
            memory_before = set(notification_memory)
            notifications.extend(complete_series_notifications(ref.match_id, state, []))
            generated_memory_keys.update(
                set(notification_memory).difference(memory_before)
            )

    if any(item.kind == "series_end" for item in notifications):
        try:
            await reconcile_unsettled_predictions(
                exclude_matches={(event_id, str(match_id)) for match_id in matches},
            )
        except Exception:
            logger.exception("CS 比赛结束补结算失败，保留下注等待后续结束事件或启动")

    try:
        prediction_candidates = (
            await reserve_prediction_team_labels(event_id, matches)
            if any(item.kind == "prediction_open" for item in notifications)
            else {}
        )
        loaded_matches = {str(match.match_id): match for _, match in loaded}
        target_notifications = []
        for target, settings in target_settings:
            selected = notifications_for_event_target(notifications, settings)
            if target.get("kind") == "group":
                selected = prediction_notifications_with_labels(
                    selected,
                    prediction_candidates.get(str(target.get("id")), []),
                    loaded_matches,
                )
                selected = await with_prediction_settlement_notifications(
                    event_id, str(target["id"]), selected,
                )
            target_notifications.append((target, selected))
    except Exception:
        # 生成通知失败需撤销新记忆，留待下一轮重试。
        for key in generated_memory_keys:
            notification_memory.pop(key, None)
        raise
    target_notifications = [
        (target, notifications_for_target)
        for target, notifications_for_target in target_notifications
        if notifications_for_target
    ]
    if target_notifications:
        if not await broadcast_target_notifications(target_notifications):
            # 全部发送失败仅撤销本轮新键，保留已成功通知的记忆。
            for key in generated_memory_keys:
                notification_memory.pop(key, None)
            return

    first_started_at = entry.get("first_match_started_at")
    if observed_first_start is not None and not parse_datetime(first_started_at):
        first_started_at = observed_first_start.isoformat()
        entry["first_match_started_at"] = first_started_at
        entry["status"] = EVENT_STATUS_ONGOING

    event_snapshot = {**entry, "matches": matches}
    event_finished = event_ended(event_snapshot)
    status = EVENT_STATUS_FINISHED if event_finished else event_status(entry)
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
            clear_notification_memory(match_id)


async def poll_subscriptions() -> None:
    """轮询赛事订阅并推送状态变化。"""
    cleanup_notification_memory()
    entries = await list_active_events()
    for event_id, entry in entries.items():
        try:
            if event_status(entry) == EVENT_STATUS_WAITING:
                activated = await activate_waiting_event(event_id, entry)
                if not activated and not event_prediction_due(entry):
                    continue
            await poll_event_subscription(event_id, entry)
        except HltvError as exc:
            logger.warning("轮询 HLTV 赛事 %s 失败：%s", event_id, exc)
        except Exception:
            logger.exception("处理 HLTV 赛事订阅失败：%s", event_id)
