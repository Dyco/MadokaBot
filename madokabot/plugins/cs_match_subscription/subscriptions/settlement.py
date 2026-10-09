"""未结算竞猜恢复模块。"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ..client import fetch_match
from ..models import MatchData
from ..prediction import (
    get_prediction_settlement_reports,
    list_unsettled_prediction_matches,
    save_prediction_notification_text,
    settle_match_predictions,
)
from ..storage import get_prediction_settlement_state, mark_prediction_settled
from .delivery import available_bots, broadcast_target_notifications
from .notifications import (
    MatchNotification,
    final_message,
    prediction_settlement_messages,
)
from .rating import render_check_rating_messages
from .state import match_winner


_RECONCILIATION_LOCK = asyncio.Lock()


async def reconcile_unsettled_predictions(
    *, exclude_matches: set[tuple[str, str]] | None = None,
) -> int:
    """未结算竞猜恢复方法。"""
    settled_matches = 0
    async with _RECONCILIATION_LOCK:
        loaded_matches = {}
        pending = await list_unsettled_prediction_matches()
        for event_id, match_id in pending:
            try:
                state = await get_prediction_settlement_state(event_id, match_id)
                match = await fetch_match(
                    match_id, page_url=str(state.get("url") or "") or None
                )
                if str(match.match_id) != match_id:
                    logger.warning("CS 补结算比赛编号不匹配：%s", match_id)
                    continue
                if match.event_url:
                    event_path = urlparse(match.event_url).path.strip("/").split("/")
                    if (
                        len(event_path) >= 2
                        and event_path[0] == "events"
                        and event_path[1] != event_id
                    ):
                        logger.warning(
                            "CS 补结算赛事编号不匹配：event_id=%s match_id=%s",
                            event_id, match_id,
                        )
                        continue
                if not match.is_finished:
                    continue
                loaded_matches[(event_id, match_id)] = match
                winner_name = match_winner(match)
                if not winner_name:
                    logger.warning("CS 比赛已结束但胜者暂不可确认，保留竞猜：%s", match_id)
                    continue
                result = await settle_match_predictions(
                    event_id, match_id, winner_name,
                    final_text=final_message(match).extract_plain_text(),
                )
                if not result["settled_count"]:
                    continue
                settled_matches += 1
                logger.info(
                    "CS 未结算竞猜已处理：event_id=%s match_id=%s winner=%s",
                    event_id, match_id, winner_name,
                )
                try:
                    await mark_prediction_settled(event_id, match_id, winner_name)
                except Exception:
                    logger.exception("CS 积分已结算，但竞猜快照同步失败：%s", match_id)
            except Exception:
                logger.exception("CS 未结算竞猜检查失败，保留下注等待下次触发：%s", match_id)
        await send_pending_prediction_notifications(
            exclude_matches=exclude_matches, matches=loaded_matches,
        )
    return settled_matches


async def with_prediction_settlement_notifications(
    event_id: str, group_id: str, notifications: list[MatchNotification],
) -> list[MatchNotification]:
    """在比赛结束节点后合并本群及其他群的结算节点。"""
    selected = []
    for item in notifications:
        selected.append(item)
        if item.kind != "series_end" or not item.match_id:
            continue
        reports = await get_prediction_settlement_reports(
            event_id=event_id, match_id=item.match_id, group_id=group_id,
        )
        if reports:
            await save_prediction_notification_text(
                event_id, item.match_id, item.message.extract_plain_text(),
            )
            selected.extend(
                MatchNotification("prediction_settlement", message, item.match_id, event_id)
                for message in prediction_settlement_messages(reports[0])
            )
    return selected


async def send_pending_prediction_notifications(
    *, exclude_matches: set[tuple[str, str]] | None = None,
    matches: dict[tuple[str, str], MatchData] | None = None,
    ready_only: bool = False,
) -> None:
    """沿用群通知凭据补发比赛结束、本群及其他群结算节点。"""
    if not list(available_bots()):
        return
    excluded = exclude_matches or set()
    reports = await get_prediction_settlement_reports(pending_only=True)
    by_match: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for report in reports:
        key = (report["event_id"], report["match_id"])
        if key not in excluded:
            by_match.setdefault(key, []).append(report)
    for (event_id, match_id), group_reports in by_match.items():
        try:
            match = (matches or {}).get((event_id, match_id))
            text = group_reports[0]["final_text"]
            if not text:
                if ready_only:
                    continue
                match = match or await fetch_match(match_id)
                if str(match.match_id) != match_id or not match.is_finished:
                    continue
                if match.event_url:
                    event_path = urlparse(match.event_url).path.strip("/").split("/")
                    if (
                        len(event_path) >= 2
                        and event_path[0] == "events"
                        and event_path[1] != event_id
                    ):
                        logger.warning("CS 待发送结算通知赛事不匹配：%s", match_id)
                        continue
                text = final_message(match).extract_plain_text()
                await save_prediction_notification_text(event_id, match_id, text)
            rating_messages = []
            if match is not None:
                try:
                    rating_messages = await render_check_rating_messages(match)
                except Exception:
                    logger.exception("CS 补结算 Rating 渲染失败，仅发送比分与结算：%s", match_id)
            target_notifications = []
            for report in group_reports:
                nodes = [
                    MatchNotification("series_end", Message(MessageSegment.text(text)), match_id, event_id),
                ]
                nodes.extend(
                    MatchNotification("prediction_settlement", message, match_id, event_id)
                    for message in prediction_settlement_messages(report)
                )
                nodes.extend(
                    MatchNotification("series_rating", message, match_id, event_id)
                    for message in rating_messages
                )
                target_notifications.append(({"kind": "group", "id": report["group_id"]}, nodes))
            await broadcast_target_notifications(target_notifications)
        except Exception:
            logger.exception("CS 结算通知发送失败，保留凭据等待重试：%s", match_id)
