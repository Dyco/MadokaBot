"""每日次数与投胎结果的事务服务。"""

from zoneinfo import ZoneInfo

from nonebot_plugin_datastore import create_session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from madokabot.core.db.base import shanghai_now
from madokabot.core.user.models import UserStats
from .models import ChinaRebornRecord, RebornRecord
from .simulation import simulate_rebirth

REROLL_COST = 5


async def reborn_today(user_id: str, *, china: bool = False) -> tuple[dict, bool]:
    """返回所选模式在上海日期当天的唯一结果，两种模式分别免费计次。"""
    today = shanghai_now().astimezone(ZoneInfo("Asia/Shanghai")).date()
    model = ChinaRebornRecord if china else RebornRecord
    key = (user_id, today)
    async with create_session() as session:
        record = await session.get(model, key)
        if record is not None:
            return dict(record.result), False

        result = simulate_rebirth(china=True) if china else simulate_rebirth()
        result["date"] = today.isoformat()
        session.add(model(user_id=user_id, reborn_date=today, result=result))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            record = await session.get(model, key)
            if record is None:
                raise
            return dict(record.result), False
        return result, True


async def reroll_today(user_id: str, *, china: bool = False) -> tuple[dict, int]:
    """原子扣除积分并替换所选模式当天的结果，失败时整笔回滚。"""
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

        record = await session.get(model, (user_id, today))
        if record is None:
            command = "投胎中国" if china else "投胎"
            raise ValueError(f"今天还没有进行{command}，请先使用{command}命令领取本模式的免费投胎。")
        result = simulate_rebirth(china=True) if china else simulate_rebirth()
        result["date"] = today.isoformat()
        record.result = result
        remaining = await session.scalar(
            select(UserStats.points).where(UserStats.user_id == user_id)
        )
        await session.commit()
        return result, remaining
