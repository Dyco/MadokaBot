# -*- coding: utf-8 -*-
"""CS 赛事竞猜记录、结算和排行榜。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nonebot import logger
from nonebot_plugin_datastore import create_session
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from madokabot.core.user.models import UserStats

from .config import config
from .prediction_labels import TEAM_LETTERS, prediction_team_labels
from .prediction_models import CsPrediction, CsPredictionNotification
from .storage import (
    get_prediction_match_context,
    list_open_prediction_matches,
)

_SETTLEMENT_LOCK = asyncio.Lock()
_PREDICTION_TIMEOUT = timedelta(hours=12)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def prediction_odds(team_count: int, opponent_count: int) -> Decimal:
    """按跨群双方人数计算奖励倍率，从第二人起调整并限制最低值。"""
    return max(
        config.cs_prediction_min_odds,
        config.cs_prediction_base_odds
        - config.cs_prediction_odds_decrement * max(0, team_count - 1)
        + config.cs_prediction_odds_increment * max(0, opponent_count - 1),
    )


async def _finish_prediction(
    session: AsyncSession,
    row: CsPrediction,
    *,
    payout: int,
    result: str,
    now: datetime,
) -> bool:
    """竞猜结算方法。"""
    claimed = await session.execute(
        update(CsPrediction)
        .where(
            CsPrediction.event_id == row.event_id,
            CsPrediction.match_id == row.match_id,
            CsPrediction.group_id == row.group_id,
            CsPrediction.user_id == row.user_id,
            CsPrediction.result == "open",
        )
        .values(
            payout=payout,
            net_points=payout - row.points,
            result=result,
            settled_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        return False
    if payout:
        await session.execute(
            update(UserStats)
            .where(UserStats.user_id == row.user_id)
            .values(points=UserStats.points + payout)
        )
    return True


class PredictionError(RuntimeError):
    """竞猜参数或状态不符合要求。"""


async def _record_prediction_notifications(
    session: AsyncSession,
    rows: list[CsPrediction],
    winner_name: str,
    final_text: str = "",
) -> None:
    """竞猜通知凭据保存方法。"""
    keys = {(row.event_id, row.match_id, row.group_id) for row in rows}
    for event_id, match_id, group_id in keys:
        if await session.get(CsPredictionNotification, (event_id, match_id, group_id)):
            continue
        session.add(CsPredictionNotification(
            event_id=event_id, match_id=match_id, group_id=group_id,
            winner_name=winner_name, final_text=final_text,
        ))


def _normalize_team(value: str) -> str:
    """规范化队伍名称用于比较。"""
    return " ".join(
        str(value).strip().strip("{}").strip().casefold().split()
    )


def _select_team(
    value: str,
    team_names: list[str],
    team_slots: list[int],
) -> str | None:
    """竞猜队伍选择方法。"""
    if len(team_names) < 2:
        return None
    normalized = _normalize_team(value)
    selector = normalized
    for prefix in ("team", "队伍"):
        if selector.startswith(prefix):
            selector = selector[len(prefix):].strip()
            break
    slot = None
    if len(selector) == 1 and selector.upper() in TEAM_LETTERS:
        slot = TEAM_LETTERS.index(selector.upper()) + 1
    elif selector.isascii() and selector.isdigit():
        slot = int(selector)
    if slot is not None:
        return next(
            (
                team_names[index]
                for index, candidate_slot in enumerate(team_slots[:2])
                if candidate_slot == slot
            ),
            None,
        )
    for team_name in team_names[:2]:
        if _normalize_team(team_name) == normalized:
            return team_name
    return None


async def place_prediction(
    group_id: str,
    user_id: str,
    team_input: str,
    points: int,
) -> dict[str, Any]:
    """为当前群唯一匹配的开放比赛记录一笔竞猜。"""
    if points <= 0:
        raise PredictionError("竞猜积分必须是大于0的整数。")

    candidates = await list_open_prediction_matches(group_id)
    candidates = [
        candidate
        for candidate in candidates
        if len(candidate.get("team_names") or []) >= 2
    ]
    if not candidates:
        raise PredictionError("当前没有正在接受竞猜的比赛。")

    selected: dict[str, Any] | None = None
    selected_team = ""
    for candidate in candidates:
        team_names = [str(value) for value in candidate["team_names"][:2]]
        team_name = _select_team(team_input, team_names, candidate.get("team_slots") or [])
        if team_name is None:
            continue
        if selected is not None:
            raise PredictionError("该队伍对应多场开放竞猜，请使用通知中的竞猜编号选择比赛。")
        selected = candidate
        selected_team = team_name
    if selected is None:
        raise PredictionError("未找到对应队伍，请使用当前竞猜编号（如 teamA、team1）或完整队伍名。")

    event_id = str(selected["event_id"])
    match_id = str(selected["match_id"])
    normalized_group_id = str(group_id)
    normalized_user_id = str(user_id)
    async with create_session() as session:
        user = await session.get(UserStats, normalized_user_id)
        if user is None:
            raise PredictionError("请先发送“注册”完成用户注册。")

        existing = await session.scalar(
            select(CsPrediction).where(
                CsPrediction.event_id == event_id,
                CsPrediction.match_id == match_id,
                CsPrediction.user_id == normalized_user_id,
            )
        )
        if existing is not None:
            raise PredictionError("你已经预测过这场比赛，每人只能预测一次。")

        deduction = await session.execute(
            update(UserStats)
            .where(
                UserStats.user_id == normalized_user_id,
                UserStats.points >= points,
            )
            .values(points=UserStats.points - points)
        )
        if deduction.rowcount != 1:
            raise PredictionError(
                f"您的当前积分为：{user.points}，参与数值已超额，请重试。"
            )

        session.add(
            CsPrediction(
                event_id=event_id,
                match_id=match_id,
                group_id=normalized_group_id,
                user_id=normalized_user_id,
                team_name=selected_team,
                team1_name=str(selected["team_names"][0]),
                team2_name=str(selected["team_names"][1]),
                points=points,
            )
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise PredictionError("你已经预测过这场比赛，每人只能预测一次。") from exc

    return {
        "event_id": event_id,
        "match_id": match_id,
        "event_name": str(selected.get("event_name") or ""),
        "team_name": selected_team,
        "points": points,
    }


async def get_prediction_summary(
    event_id: str,
    match_id: str,
    *,
    group_id: str | None = None,
) -> dict[str, Any]:
    """统计比赛的竞猜人数和下注积分。"""
    conditions = [
        CsPrediction.event_id == str(event_id),
        CsPrediction.match_id == str(match_id),
    ]
    if group_id is not None:
        conditions.append(CsPrediction.group_id == str(group_id))

    async with create_session() as session:
        rows = list(
            (
                await session.scalars(
                    select(CsPrediction).where(*conditions)
                )
            ).all()
        )

    by_team: dict[str, dict[str, int]] = {}
    for row in rows:
        summary = by_team.setdefault(row.team_name, {"count": 0, "points": 0})
        summary["count"] += 1
        summary["points"] += row.points
    return {
        "teams": by_team,
        "total_count": len(rows),
        "total_points": sum(row.points for row in rows),
    }


async def settle_match_predictions(
    event_id: str,
    match_id: str,
    winner_name: str,
    *,
    final_text: str = "",
) -> dict[str, Any]:
    """按双方跨群人数结算动态奖励并退回胜者本金，小数奖励向下取整。"""
    normalized_winner = _normalize_team(winner_name)
    async with _SETTLEMENT_LOCK, create_session() as session:
        rows = list(
            (
                await session.scalars(
                    select(CsPrediction).where(
                        CsPrediction.event_id == str(event_id),
                        CsPrediction.match_id == str(match_id),
                        CsPrediction.result == "open",
                    )
                )
            ).all()
        )
        total_points = sum(row.points for row in rows)
        winner_rows = [
            row for row in rows if _normalize_team(row.team_name) == normalized_winner
        ]
        winner_points = sum(row.points for row in winner_rows)
        odds = prediction_odds(len(winner_rows), len(rows) - len(winner_rows))
        total_payout = 0
        settled_count = 0
        claimed_rows = []
        now = datetime.now(timezone.utc)

        for row in rows:
            is_winner = row in winner_rows
            payout = (
                row.points + int(row.points * odds)
                if is_winner
                else 0
            )
            if await _finish_prediction(
                session,
                row,
                payout=payout,
                result="win" if is_winner else "lose",
                now=now,
            ):
                total_payout += payout
                settled_count += 1
                claimed_rows.append(row)
        await _record_prediction_notifications(
            session, claimed_rows, winner_name, final_text,
        )
        await session.commit()

    return {
        "total_count": len(rows),
        "total_points": total_points,
        "odds": odds,
        "winner_count": len(winner_rows),
        "winner_points": winner_points,
        "total_payout": total_payout,
        "settled_count": settled_count,
    }


async def list_unsettled_prediction_matches() -> list[tuple[str, str]]:
    """未结算竞猜查询方法。"""
    async with create_session() as session:
        rows = (await session.execute(
            select(CsPrediction.event_id, CsPrediction.match_id)
            .where(CsPrediction.result == "open")
            .distinct()
            .order_by(CsPrediction.event_id, CsPrediction.match_id)
        )).all()
    return [(str(event_id), str(match_id)) for event_id, match_id in rows]


async def get_prediction_settlement_reports(
    *,
    event_id: str | None = None,
    match_id: str | None = None,
    group_id: str | None = None,
    pending_only: bool = False,
) -> list[dict[str, Any]]:
    """按目标群拆分结算名单，其他群按净收益排序取前二十名。"""
    statement = select(CsPredictionNotification)
    for column, value in (
        (CsPredictionNotification.event_id, event_id),
        (CsPredictionNotification.match_id, match_id),
    ):
        if value is not None:
            statement = statement.where(column == str(value))
    if pending_only:
        statement = statement.where(CsPredictionNotification.sent.is_(False))
    reports = []
    match_players = {}
    async with create_session() as session:
        receipts = list((await session.scalars(statement)).all())
        if group_id is not None:
            target_receipts = []
            seen_matches = set()
            for receipt in receipts:
                match_key = (receipt.event_id, receipt.match_id)
                if match_key in seen_matches:
                    continue
                seen_matches.add(match_key)
                target = await session.get(
                    CsPredictionNotification, (*match_key, str(group_id)),
                )
                if target is None:
                    # 无本群下注时也保存凭据，使其他群结算通知沿用发送去重。
                    target = CsPredictionNotification(
                        event_id=receipt.event_id, match_id=receipt.match_id,
                        group_id=str(group_id), winner_name=receipt.winner_name,
                        final_text=receipt.final_text,
                    )
                    session.add(target)
                if not pending_only or not target.sent:
                    target_receipts.append(target)
            receipts = target_receipts
        for receipt in receipts:
            match_key = (receipt.event_id, receipt.match_id)
            if match_key not in match_players:
                rows = (await session.execute(
                    select(CsPrediction, UserStats)
                    .outerjoin(UserStats, CsPrediction.user_id == UserStats.user_id)
                    .where(
                        CsPrediction.event_id == receipt.event_id,
                        CsPrediction.match_id == receipt.match_id,
                        CsPrediction.result != "open",
                    )
                    .order_by(CsPrediction.net_points.desc(), CsPrediction.user_id)
                )).all()
                match_players[match_key] = [{
                    "name": (
                        str(user.display_name or user.qq_nickname or "").strip() if user else ""
                    ) + f"({_masked_user_id(row.user_id)})",
                    "group_id": row.group_id,
                    "team_name": row.team_name, "points": row.points,
                    "payout": row.payout, "net_points": row.net_points,
                    "result": row.result,
                } for row, user in rows]
            players = match_players[match_key]
            reports.append({
                "event_id": receipt.event_id, "match_id": receipt.match_id,
                "group_id": receipt.group_id, "winner_name": receipt.winner_name,
                "final_text": receipt.final_text, "sent": receipt.sent,
                "players": [player for player in players if player["group_id"] == receipt.group_id],
                "other_players": [player for player in players if player["group_id"] != receipt.group_id][:20],
            })
        if group_id is not None:
            await session.commit()
    return reports


async def save_prediction_notification_text(event_id: str, match_id: str, text: str) -> None:
    """保存原结束消息。"""
    async with create_session() as session:
        await session.execute(update(CsPredictionNotification).where(
            CsPredictionNotification.event_id == str(event_id),
            CsPredictionNotification.match_id == str(match_id),
        ).values(final_text=text))
        await session.commit()


async def prediction_notification_was_sent(event_id: str, match_id: str, group_id: str) -> bool:
    """竞猜通知发送状态查询方法。"""
    async with create_session() as session:
        receipt = await session.get(
            CsPredictionNotification, (str(event_id), str(match_id), str(group_id)),
        )
        return bool(receipt and receipt.sent)


async def mark_prediction_notification_sent(event_id: str, match_id: str, group_id: str) -> None:
    """群合并消息发送成功后标记通知已送达。"""
    async with create_session() as session:
        await session.execute(update(CsPredictionNotification).where(
            CsPredictionNotification.event_id == str(event_id),
            CsPredictionNotification.match_id == str(match_id),
            CsPredictionNotification.group_id == str(group_id),
        ).values(sent=True))
        await session.commit()


async def refund_expired_predictions(*, now: datetime | None = None) -> int:
    """过期竞猜退款方法。"""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI_TZ)
    # SQLite不保存时区，created_at按上海时间解释。
    cutoff = (current.astimezone(_SHANGHAI_TZ) - _PREDICTION_TIMEOUT).replace(tzinfo=None)
    refunded_count = 0
    async with _SETTLEMENT_LOCK:
        async with create_session() as session:
            expired_matches = list((await session.execute(
                select(CsPrediction.event_id, CsPrediction.match_id)
                .where(CsPrediction.result == "open")
                .group_by(CsPrediction.event_id, CsPrediction.match_id)
                .having(func.min(CsPrediction.created_at) <= cutoff)
            )).all())

        for event_id, match_id in expired_matches:
            async with create_session() as session:
                rows = list((await session.scalars(
                    select(CsPrediction).where(
                        CsPrediction.event_id == event_id,
                        CsPrediction.match_id == match_id,
                        CsPrediction.result == "open",
                    )
                )).all())
                count = points = 0
                for row in rows:
                    if await _finish_prediction(
                        session, row, payout=row.points, result="refund", now=current
                    ):
                        count += 1
                        points += row.points
                await session.commit()
            if count:
                refunded_count += count
                logger.info(
                    f"CS 竞猜超过 12 小时未结算，已自动退款："
                    f"event_id={event_id} match_id={match_id} "
                    f"下注笔数={count} 退回积分={points}"
                )
    return refunded_count


async def get_prediction_detail(
    group_id: str,
    match_id: str,
) -> dict[str, Any] | None:
    """生成指定群查看竞猜详情所需的数据。"""
    context = await get_prediction_match_context(group_id, match_id)
    if context is None:
        return None

    state = context["state"]
    if state.get("completed"):
        status_text = "已结束"
    elif state.get("started_sent"):
        status_text = "比赛中"
    elif state.get("prediction_open"):
        status_text = "预测中"
    else:
        status_text = "未开始"

    summary = await get_prediction_summary(
        str(context["event_id"]),
        str(match_id),
        group_id=str(group_id),
    )
    global_summary = await get_prediction_summary(str(context["event_id"]), str(match_id))
    team_names = [str(value) for value in state.get("team_names") or []]
    odds = {}
    for team_name in team_names:
        team_count = sum(
            team_summary["count"]
            for name, team_summary in global_summary["teams"].items()
            if _normalize_team(name) == _normalize_team(team_name)
        )
        odds[team_name] = prediction_odds(
            team_count, global_summary["total_count"] - team_count,
        )
    return {
        "event_id": str(context["event_id"]),
        "match_id": str(match_id),
        "status": status_text,
        "team_names": team_names,
        "team_labels": (
            prediction_team_labels(state, str(group_id))
            if state.get("prediction_open") and not state.get("prediction_closed")
            else []
        ),
        "summary": summary,
        "winner_name": str(state.get("winner_name") or ""),
        "odds": odds,
    }


def _masked_user_id(user_id: str) -> str:
    """将 QQ 号按前两位和后两位显示。"""
    value = str(user_id)
    if len(value) <= 4:
        return value
    return f"{value[:2]}***{value[-2:]}"


def _prediction_nickname(nickname: str, user_id: str) -> str:
    """竞猜卡片昵称最多保留八个字符，无昵称时展示脱敏账号。"""
    if not nickname:
        return f"用户({_masked_user_id(user_id)})"
    return f"{nickname[:8]}..." if len(nickname) > 8 else nickname


async def get_prediction_personal_records(user_id: str) -> dict[str, Any]:
    """汇总个人成绩，并读取最近三十条记录保存的对阵和获胜队伍。"""
    settled = CsPrediction.settled_at.is_not(None)
    won = settled & (CsPrediction.result == "win")
    lost = settled & (CsPrediction.result == "lose")
    completed = won | lost
    refunded = settled & (CsPrediction.result == "refund")
    async with create_session() as session:
        totals = (
            await session.execute(select(
                func.count().label("total_count"),
                func.coalesce(func.sum(case((won, 1), else_=0)), 0).label("wins"),
                func.coalesce(func.sum(case((lost, 1), else_=0)), 0).label("losses"),
                func.coalesce(func.sum(case((refunded, 1), else_=0)), 0)
                .label("refund_count"),
                func.coalesce(
                    func.sum(case((completed, CsPrediction.net_points), else_=0)), 0,
                ).label("net_points"),
            ).where(CsPrediction.user_id == str(user_id)))
        ).one()
        rows = (await session.scalars(
            select(CsPrediction)
            .where(CsPrediction.user_id == str(user_id))
            .order_by(
                CsPrediction.created_at.desc(), CsPrediction.event_id.desc(),
                CsPrediction.match_id.desc(), CsPrediction.group_id.desc(),
            )
            .limit(30)
        )).all()
        user = await session.get(UserStats, str(user_id))
        nickname = str(user.display_name or user.qq_nickname or "").strip() if user else ""
        entries = []
        for row in rows:
            result = row.result if row.settled_at is not None else "open"
            teams = [row.team1_name or row.team_name, row.team2_name or "未知队伍"]
            winner_name = ""
            if result == "win":
                winner_name = row.team_name
            elif result == "lose" and row.team1_name and row.team2_name:
                winner_name = (
                    row.team2_name if _normalize_team(row.team1_name) == _normalize_team(row.team_name)
                    else row.team1_name
                )
            entries.append({
                "match_id": row.match_id,
                "team_name": row.team_name,
                "team_names": teams,
                "winner_name": winner_name,
                "points": row.points,
                "created_at": row.created_at.strftime("%Y-%m-%d %H:%M"),
                "result": result,
                "result_label": {
                    "win": "获胜", "lose": "失败", "refund": "已退款",
                }.get(result, "未结算"),
                "net_points": row.net_points if result in {"win", "lose"} else 0,
            })

    settled_count = totals.wins + totals.losses
    return {
        "nickname": _prediction_nickname(nickname, user_id),
        "masked_user_id": _masked_user_id(user_id),
        "avatar_url": f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640",
        "total_count": totals.total_count,
        "settled_count": settled_count,
        "wins": totals.wins,
        "losses": totals.losses,
        "refund_count": totals.refund_count,
        "pending_count": totals.total_count - settled_count - totals.refund_count,
        "win_rate": f"{totals.wins / settled_count * 100:.0f}%" if settled_count else "0%",
        "net_points": totals.net_points,
        "entries": entries,
    }


async def get_prediction_ranking(
    scope: str,
    group_id: str,
) -> list[dict[str, Any]]:
    """汇总已结算竞猜并返回前二十名。"""
    async with create_session() as session:
        statement = select(CsPrediction).where(
            CsPrediction.result.in_(("win", "lose")),
            CsPrediction.settled_at.is_not(None),
        )
        if scope == "group":
            statement = statement.where(CsPrediction.group_id == str(group_id))
        rows = list((await session.scalars(statement)).all())
        user_ids = {row.user_id for row in rows}
        users = {}
        if user_ids:
            users = {
                user.user_id: user
                for user in (
                    await session.scalars(
                        select(UserStats).where(UserStats.user_id.in_(user_ids))
                    )
                ).all()
            }

    aggregates: dict[str, dict[str, int]] = {}
    for row in rows:
        item = aggregates.setdefault(
            row.user_id,
            {"wins": 0, "total": 0, "net_points": 0},
        )
        item["wins"] += row.result == "win"
        item["total"] += 1
        item["net_points"] += row.net_points

    ranked = sorted(
        aggregates.items(),
        key=lambda item: (
            -item[1]["wins"],
            -item[1]["net_points"],
            -(item[1]["wins"] / item[1]["total"] if item[1]["total"] else 0),
            -item[1]["total"],
            item[0],
        ),
    )[:20]
    result: list[dict[str, Any]] = []
    for rank, (user_id, aggregate) in enumerate(ranked, start=1):
        user = users.get(user_id)
        nickname = str(user.display_name or user.qq_nickname or "").strip() if user else ""
        win_rate = (
            aggregate["wins"] / aggregate["total"] * 100
            if aggregate["total"]
            else 0
        )
        result.append(
            {
                "rank": rank,
                "user_id": user_id,
                "nickname": _prediction_nickname(nickname, user_id),
                "win_rate": f"{win_rate:.0f}%({aggregate['wins']}次)",
                "total_count": aggregate["total"],
                "net_points": aggregate["net_points"],
                "avatar_url": f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640",
            }
        )
    return result


__all__ = [
    "PredictionError",
    "prediction_odds",
    "get_prediction_detail",
    "get_prediction_ranking",
    "get_prediction_personal_records",
    "get_prediction_summary",
    "get_prediction_settlement_reports",
    "save_prediction_notification_text",
    "prediction_notification_was_sent",
    "mark_prediction_notification_sent",
    "list_unsettled_prediction_matches",
    "place_prediction",
    "refund_expired_predictions",
    "settle_match_predictions",
]
