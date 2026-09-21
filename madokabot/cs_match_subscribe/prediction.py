# -*- coding: utf-8 -*-
"""CS 赛事竞猜记录、结算和排行榜。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nonebot_plugin_datastore import create_session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..madoka_bundle.db.models import CsPrediction, UserStats
from .storage import (
    get_prediction_match_context,
    list_open_prediction_matches,
)


class PredictionError(RuntimeError):
    """竞猜参数或状态不符合要求。"""


def _normalize_team(value: str) -> str:
    """规范化队伍名称用于比较。"""
    return " ".join(
        str(value).strip().strip("{}").strip().casefold().split()
    )


def _select_team(value: str, team_names: list[str]) -> str | None:
    """从 A/B 或队伍名中选出比赛队伍。"""
    if len(team_names) < 2:
        return None
    normalized = _normalize_team(value)
    if normalized in {"a", "team a", "teama", "队伍a", "队伍 a"}:
        return team_names[0]
    if normalized in {"b", "team b", "teamb", "队伍b", "队伍 b"}:
        return team_names[1]
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
        team_name = _select_team(team_input, team_names)
        if team_name is None:
            continue
        if selected is not None:
            raise PredictionError("当前有多场比赛同时接受竞猜，请稍后再试。")
        selected = candidate
        selected_team = team_name
    if selected is None:
        raise PredictionError("未找到对应队伍，请使用 A、B 或完整队伍名。")

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
                CsPrediction.group_id == normalized_group_id,
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
    """统计比赛的竞猜人数和积分池。"""
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


async def refund_uncontested_predictions(
    event_id: str,
    match_id: str,
    team_names: list[str],
) -> dict[str, Any]:
    """单方无人下注时退回本场所有未结算竞猜积分。"""
    normalized_teams = [
        _normalize_team(team_name)
        for team_name in team_names[:2]
        if _normalize_team(team_name)
    ]
    if len(normalized_teams) < 2:
        return {
            "refunded": False,
            "total_count": 0,
            "total_points": 0,
            "refunded_points": 0,
        }

    async with create_session() as session:
        rows = list(
            (
                await session.scalars(
                    select(CsPrediction).where(
                        CsPrediction.event_id == str(event_id),
                        CsPrediction.match_id == str(match_id),
                    )
                )
            ).all()
        )
        open_rows = [row for row in rows if row.result == "open"]
        refunded_rows = [row for row in rows if row.result == "refund"]
        if not open_rows:
            return {
                "refunded": bool(refunded_rows),
                "total_count": len(rows),
                "total_points": sum(row.points for row in rows),
                "refunded_points": sum(row.points for row in refunded_rows),
            }

        points_by_team: dict[str, int] = {}
        for row in open_rows:
            normalized_name = _normalize_team(row.team_name)
            points_by_team[normalized_name] = (
                points_by_team.get(normalized_name, 0) + row.points
            )
        if all(points_by_team.get(team_name, 0) > 0 for team_name in normalized_teams):
            return {
                "refunded": False,
                "total_count": len(open_rows),
                "total_points": sum(row.points for row in open_rows),
                "refunded_points": 0,
            }

        now = datetime.now(timezone.utc)
        refunded_points = 0
        for row in open_rows:
            row.payout = row.points
            row.net_points = 0
            row.result = "refund"
            row.settled_at = now
            refunded_points += row.points
            user = await session.get(UserStats, row.user_id)
            if user is not None:
                user.points += row.points
        await session.commit()

    return {
        "refunded": True,
        "total_count": len(open_rows),
        "total_points": refunded_points,
        "refunded_points": refunded_points,
    }


async def settle_match_predictions(
    event_id: str,
    match_id: str,
    winner_name: str,
) -> dict[str, Any]:
    """结算比赛竞猜，胜方均分本场总投注池。"""
    normalized_winner = _normalize_team(winner_name)
    async with create_session() as session:
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
        payout = total_points // len(winner_rows) if winner_rows else 0
        now = datetime.now(timezone.utc)

        for row in rows:
            row.payout = payout if row in winner_rows else 0
            row.net_points = row.payout - row.points
            row.result = "win" if row in winner_rows else "lose"
            row.settled_at = now
            if row.payout:
                user = await session.get(UserStats, row.user_id)
                if user is not None:
                    user.points += row.payout
        await session.commit()

    return {
        "total_count": len(rows),
        "total_points": total_points,
        "winner_count": len(winner_rows),
        "payout_per_winner": payout,
    }


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
    return {
        "event_id": str(context["event_id"]),
        "match_id": str(match_id),
        "status": status_text,
        "team_names": [str(value) for value in state.get("team_names") or []],
        "summary": summary,
        "winner_name": str(state.get("winner_name") or ""),
        "payout_per_winner": int(state.get("prediction_payout") or 0),
    }


def _masked_user_id(user_id: str) -> str:
    """将 QQ 号按前两位和后两位显示。"""
    value = str(user_id)
    if len(value) <= 4:
        return value
    return f"{value[:2]}***{value[-2:]}"


async def get_prediction_ranking(
    scope: str,
    group_id: str,
) -> list[dict[str, Any]]:
    """按胜场、净积分、胜率和参与次数生成前十名。"""
    async with create_session() as session:
        statement = select(CsPrediction).where(CsPrediction.result != "open")
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
    )[:10]
    result: list[dict[str, Any]] = []
    for rank, (user_id, aggregate) in enumerate(ranked, start=1):
        user = users.get(user_id)
        nickname = str(user.qq_nickname or "").strip() if user else ""
        display_name = nickname or f"用户({_masked_user_id(user_id)})"
        if len(display_name) > 6 and nickname:
            display_name = f"{nickname[:6]}..."
        win_rate = (
            aggregate["wins"] / aggregate["total"] * 100
            if aggregate["total"]
            else 0
        )
        result.append(
            {
                "rank": rank,
                "user_id": user_id,
                "nickname": display_name,
                "win_rate": f"{win_rate:.0f}%({aggregate['wins']}次)",
                "total_count": aggregate["total"],
                "net_points": aggregate["net_points"],
                "avatar_url": f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640",
            }
        )
    return result


__all__ = [
    "PredictionError",
    "get_prediction_detail",
    "get_prediction_ranking",
    "get_prediction_summary",
    "place_prediction",
    "refund_uncontested_predictions",
    "settle_match_predictions",
]
