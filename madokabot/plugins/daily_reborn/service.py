"""每日次数与投胎结果的事务服务。"""

from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import create_session
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from madokabot.core.db.base import shanghai_now
from madokabot.core.user.models import UserStats

from .anime import ANIME_VERSION, simulate_anime
from .games import GAMES_VERSION, simulate_games
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
from .modes import RebornMode
from .regions import result_region
from .simulation import simulate_rebirth

REROLL_COST = 5
HISTORY_LIMIT = 10
RECORD_MODELS = {
    "world": RebornRecord, "china": ChinaRebornRecord, "japan": JapanRebornRecord,
    "usa": USRebornRecord, "isekai": IsekaiRebornRecord, "anime": AnimeRebornRecord, "games": GamesRebornRecord,
}


def history_entry(result: dict, count: int) -> dict:
    """按模式保存历史摘要，动漫记录分数，二游记录综合评级及其色阶。"""
    if result.get("result_version") == ANIME_VERSION:
        return {
            "count": count, "date": result["date"], "world": result["world"]["title"],
            "gender": result["gender"], "score": result["score"],
            "rating": f"{result['score']}分", "summary": result["summary"],
        }
    if result.get("mode") in {"anime", "games"}:
        entry = {
            "count": count, "date": result["date"], "world": result["world"]["title"],
            "gender": result["gender"], "rating": result["rating"]["value"], "summary": result["summary"],
        }
        if result.get("result_version") == GAMES_VERSION:
            entry["rating_tier"] = result["rating"]["tier"]
        return entry
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


async def reborn_today(
    user_id: str, *, mode: RebornMode = "world", reroll: bool = False,
) -> tuple[dict, bool, int | None]:
    """领取或查看单个模式；重开时优先使用当天免费次数。"""
    results, remaining, _ = await reborn_all_today(user_id, modes=(mode,), reroll=reroll)
    result, created = results[0]
    return result, created, remaining


async def reborn_all_today(
    user_id: str, *, modes: tuple[RebornMode, ...] = tuple(RECORD_MODELS), reroll: bool = False,
) -> tuple[list[tuple[dict, bool]], int | None, int]:
    """统一处理各模式，重开只对已领取的模式扣款，结果与扣款一起提交。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    async with create_session() as session:
        # 按固定顺序先锁定模式，再统计费用，避免并发重复领取免费次数或交叉扣款死锁。
        progresses = {mode: await lock_progress(session, user_id, mode=mode) for mode in modes}
        records = {mode: await session.get(RECORD_MODELS[mode], (user_id, today)) for mode in modes}
        cost = REROLL_COST * sum(record is not None for record in records.values()) if reroll else 0
        remaining = await deduct_reroll_points(session, user_id, cost) if cost else None
        results = []
        for mode, record in records.items():
            progress = progresses[mode]
            if record is not None and not reroll:
                result = dict(record.result) | {"reborn_count": progress.count, "reborn_history": progress.history}
                results.append((result, False))
                continue
            result = record_birth(progress, simulate_result(mode) | {"date": today.isoformat()})
            if record is None:
                session.add(RECORD_MODELS[mode](user_id=user_id, reborn_date=today, result=result))
            else:
                record.result = result
            results.append((result, True))
        await session.commit()
        return results, remaining, cost
