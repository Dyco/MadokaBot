"""许愿扣款、奖池累积与大奖结算。"""

from random import randrange

from nonebot_plugin_datastore import create_session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from madokabot.core.db.base import shanghai_now
from madokabot.core.user.models import UserStats
from .models import WishPool, WishRecord


async def execute_wish(uid: str) -> str:
    """每天仅参与一次，参与记录、扣款与奖池结算在同一事务内提交。"""
    today = shanghai_now().date()
    already_wished = "今天已经许愿过了，每天仅能许愿一次，请明天再来"
    async with create_session() as session:
        if await session.get(WishRecord, (uid, today)) is not None:
            return already_wished

        deduction = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == uid, UserStats.points >= 1)
            .values(points=UserStats.points - 1)
        )
        if deduction.rowcount != 1:
            await session.rollback()
            points = await session.scalar(
                select(UserStats.points).where(UserStats.user_id == uid)
            )
            if points is None:
                return "请先发送“注册”完成用户注册"
            # 并发请求可能在等待扣款时已用完当天机会并消耗了最后1积分。
            if await session.get(WishRecord, (uid, today)) is not None:
                return already_wished
            return "积分不足，许愿需要1积分"

        session.add(WishRecord(user_id=uid, wish_date=today))
        try:
            # 唯一主键拦截并发重复参与，冲突时撤销本次扣款。
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return already_wished

        if await session.get(WishPool, 1) is None:
            try:
                # 保存点仅回滚并发初始化冲突，保留本次扣款。
                async with session.begin_nested():
                    session.add(WishPool(id=1, points=0))
                    await session.flush()
            except IntegrityError:
                pass

        # 更新奖池取得行锁，并持有到扣款、入池与兑奖全部提交。
        await session.execute(
            update(WishPool).where(WishPool.id == 1)
            .values(points=WishPool.points + 1)
        )
        pool_points = await session.scalar(
            select(WishPool.points).where(WishPool.id == 1)
        )
        won = randrange(10000) == 0
        if won:
            await session.execute(
                update(UserStats).where(UserStats.user_id == uid)
                .values(points=UserStats.points + pool_points)
            )
            await session.execute(
                update(WishPool).where(WishPool.id == 1).values(points=0)
            )
        await session.commit()

    if won:
        return (
            f"许愿成功！已扣除1积分，恭喜触发大奖，获得许愿池全部{pool_points}积分！"
            "\n当前许愿池总积分：0"
        )
    return f"许愿未中奖，已扣除1积分，幸运+1！\n当前许愿池总积分：{pool_points}"
