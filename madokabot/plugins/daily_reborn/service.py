"""每日次数与投胎结果的事务服务。"""

from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import create_session
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from madokabot.core.db.base import shanghai_now
from madokabot.core.user.models import UserStats
from .models import ChinaRebornRecord, RebornProgress, RebornRecord
from .simulation import simulate_rebirth

REROLL_COST = 5
HISTORY_LIMIT = 10


def history_entry(result: dict, count: int) -> dict:
    """提取投胎简要记录并保留地区代码，避免仅凭名称无法区分旧历史。"""
    return {
        "count": count,
        "date": result["date"],
        "country": result["country"]["name"],
        "country_code": result["country"]["code"],
        "gender": result["gender"],
        "score": result["score"],
        "label": result["label"],
    }


async def lock_progress(session: AsyncSession, user_id: str, *, china: bool) -> RebornProgress:
    """锁定模式计数；首次使用时从现存每日记录补全可恢复的历史。"""
    mode = "china" if china else "world"
    model = ChinaRebornRecord if china else RebornRecord
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


async def reborn_today(user_id: str, *, china: bool = False) -> tuple[dict, bool]:
    """返回所选模式当天结果，新抽取才累计次数，重复查看不增加历史。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    model = ChinaRebornRecord if china else RebornRecord
    key = (user_id, today)
    async with create_session() as session:
        progress = await lock_progress(session, user_id, china=china)
        record = await session.get(model, key)
        if record is not None:
            result = dict(record.result) | {"reborn_count": progress.count, "reborn_history": progress.history}
            await session.commit()
            return result, False

        result = simulate_rebirth(china=True) if china else simulate_rebirth()
        result["date"] = today.isoformat()
        result = record_birth(progress, result)
        session.add(model(user_id=user_id, reborn_date=today, result=result))
        await session.commit()
        return result, True


async def reroll_today(user_id: str, *, china: bool = False) -> tuple[dict, int]:
    """扣款、计数、历史及当天结果一起提交，重开失败时整笔回滚。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    model = ChinaRebornRecord if china else RebornRecord
    async with create_session() as session:
        # 先条件扣款以串行处理同一账号的消费，避免并发重开透支。
        deduction = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == user_id, UserStats.points >= REROLL_COST)
            .values(points=UserStats.points - REROLL_COST)
        )
        if deduction.rowcount != 1:
            points = await session.scalar(
                select(UserStats.points).where(UserStats.user_id == user_id)
            )
            if points is None:
                raise ValueError("请先发送“注册”完成用户注册，再使用积分重开。")
            raise ValueError(f"积分不足，重开需要 {REROLL_COST} 积分，你当前只有 {points} 积分。")

        progress = await lock_progress(session, user_id, china=china)
        record = await session.get(model, (user_id, today))
        if record is None:
            command = "投胎中国" if china else "投胎"
            raise ValueError(f"今天还没有进行{command}，请先使用{command}命令领取本模式的免费投胎。")
        result = simulate_rebirth(china=True) if china else simulate_rebirth()
        result["date"] = today.isoformat()
        result = record_birth(progress, result)
        record.result = result
        remaining = await session.scalar(
            select(UserStats.points).where(UserStats.user_id == user_id)
        )
        await session.commit()
        return result, remaining
