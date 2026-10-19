"""每日次数与投胎结果的事务服务。"""

from datetime import date
from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import create_session
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from madokabot.core.db.base import shanghai_now
from madokabot.core.user.models import UserStats

from .anime import simulate_anime
from .games import simulate_games
from .isekai import simulate_isekai
from .models import (
    AnimeRebornRecord,
    ChinaRebornRecord,
    GamesRebornRecord,
    IsekaiRebornRecord,
    JapanRebornRecord,
    RebornProgress,
    RebornRecord,
    USRebornRecord,
)
from .modes import MODE_COMMANDS, RebornMode
from .regions import result_region
from .simulation import simulate_rebirth

REROLL_COST = 5
HISTORY_LIMIT = 10
RECORD_MODELS = {
    "world": RebornRecord, "china": ChinaRebornRecord, "japan": JapanRebornRecord,
    "usa": USRebornRecord, "isekai": IsekaiRebornRecord, "anime": AnimeRebornRecord, "games": GamesRebornRecord,
}


def history_entry(result: dict, count: int) -> dict:
    """按模式保存历史摘要，现实记录保留世界分区及俄罗斯当次坐标对应的区域。"""
    if result.get("mode") in {"anime", "games"}:
        return {
            "count": count, "date": result["date"], "world": result["world"]["title"],
            "gender": result["gender"], "rating": result["rating"]["value"], "summary": result["summary"],
        }
    if result.get("mode") == "isekai":
        return {
            "count": count,
            "date": result["date"],
            "world": result["world"]["title"],
            "birthplace": result["birthplace"]["name"],
            "species": result["child"]["species"],
            "gender": result["gender"],
            "family": result["household"]["name"],
        }
    return {
        "count": count,
        "date": result["date"],
        "country": result["country"]["name"],
        "country_code": result["country"]["code"],
        "world_region": result_region(result),
        "gender": result["gender"],
        "score": result["score"],
        "label": result["label"],
    }


async def lock_progress(session: AsyncSession, user_id: str, *, mode: RebornMode) -> RebornProgress:
    """锁定模式计数；首次使用时从现存每日记录补全可恢复的历史。"""
    model = RECORD_MODELS[mode]
    statement = update(RebornProgress).where(
        RebornProgress.user_id == user_id, RebornProgress.mode == mode
    ).values(count=RebornProgress.count)
    locked = await session.execute(statement)
    if locked.rowcount == 0:
        count = await session.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))
        records = (await session.scalars(
            select(model).where(model.user_id == user_id).order_by(model.reborn_date.desc()).limit(HISTORY_LIMIT)
        )).all()
        history = [
            history_entry(record.result | {"date": record.reborn_date.isoformat()}, number)
            for number, record in enumerate(reversed(records), start=count - len(records) + 1)
        ]
        try:
            # 保存点隔离首次初始化的主键竞争，保留外层扣款事务。
            async with session.begin_nested():
                session.add(RebornProgress(user_id=user_id, mode=mode, count=count, history=history))
                await session.flush()
        except IntegrityError:
            if await session.get(RebornProgress, (user_id, mode)) is None:
                raise
        await session.execute(statement)
    return await session.get(RebornProgress, (user_id, mode))


def record_birth(progress: RebornProgress, result: dict) -> dict:
    """仅在成功抽取时累加次数，保留最近十次并写入本次展示快照。"""
    progress.count += 1
    progress.history = (progress.history + [history_entry(result, progress.count)])[-HISTORY_LIMIT:]
    return result | {"reborn_count": progress.count, "reborn_history": progress.history}


def simulate_result(mode: RebornMode) -> dict:
    """按投胎模式分派资料模拟，作品身份与异世界不进入现实人口抽取。"""
    if mode == "games":
        return simulate_games()
    if mode == "anime":
        return simulate_anime()
    if mode == "isekai":
        return simulate_isekai()
    return simulate_rebirth(mode=mode)


async def save_daily_result(
    session: AsyncSession, user_id: str, today: date, *, mode: RebornMode, reroll: bool = False,
) -> tuple[dict, bool]:
    """在当前事务内读取或抽取一个模式，统一维护每日记录、计数与历史。"""
    model = RECORD_MODELS[mode]
    progress = await lock_progress(session, user_id, mode=mode)
    record = await session.get(model, (user_id, today))
    if record is not None and not reroll:
        result = dict(record.result) | {"reborn_count": progress.count, "reborn_history": progress.history}
        return result, False
    if record is None and reroll:
        command = MODE_COMMANDS[mode]
        raise ValueError(f"今天还没有进行{command}，请先使用{command}命令领取本模式的免费投胎。")

    result = simulate_result(mode)
    result["date"] = today.isoformat()
    result = record_birth(progress, result)
    if record is None:
        session.add(model(user_id=user_id, reborn_date=today, result=result))
    else:
        record.result = result
    return result, True


async def deduct_reroll_points(session: AsyncSession, user_id: str, cost: int) -> int:
    """在当前事务内条件扣款并返回余额，避免并发重开透支。"""
    deduction = await session.execute(
        update(UserStats)
        .where(UserStats.user_id == user_id, UserStats.points >= cost)
        .values(points=UserStats.points - cost)
    )
    if deduction.rowcount != 1:
        points = await session.scalar(select(UserStats.points).where(UserStats.user_id == user_id))
        if points is None:
            raise ValueError("请先发送“注册”完成用户注册，再使用积分重开。")
        raise ValueError(f"积分不足，重开需要 {cost} 积分，你当前只有 {points} 积分。")
    return await session.scalar(select(UserStats.points).where(UserStats.user_id == user_id))


async def reborn_today(user_id: str, *, mode: RebornMode = "world") -> tuple[dict, bool]:
    """返回所选模式当天结果，新抽取才累计次数，重复查看不增加历史。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    async with create_session() as session:
        result, created = await save_daily_result(session, user_id, today, mode=mode)
        await session.commit()
        return result, created


async def reroll_today(user_id: str, *, mode: RebornMode = "world") -> tuple[dict, int]:
    """扣款、计数、历史及当天结果一起提交，重开失败时整笔回滚。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    async with create_session() as session:
        remaining = await deduct_reroll_points(session, user_id, REROLL_COST)
        result, _ = await save_daily_result(session, user_id, today, mode=mode, reroll=True)
        await session.commit()
        return result, remaining


async def reborn_all_today(user_id: str, *, reroll: bool = False) -> tuple[list[dict], int | None]:
    """按模式顺序领取或重开全部投胎，任一模式失败时整体回滚。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    async with create_session() as session:
        remaining = await deduct_reroll_points(session, user_id, REROLL_COST * len(RECORD_MODELS)) if reroll else None
        results = []
        for mode in RECORD_MODELS:
            result, _ = await save_daily_result(session, user_id, today, mode=mode, reroll=reroll)
            results.append(result)
        await session.commit()
        return results, remaining
