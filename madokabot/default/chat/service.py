"""聊天调用的积分结算。"""

from nonebot_plugin_datastore import create_session
from sqlalchemy import update

from madokabot.core.user.models import UserStats


async def deduct_chat_point(uid: str) -> bool:
    """成功调用模型后扣除一积分，余额不足时不扣除。"""
    async with create_session() as session:
        deduction = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == uid, UserStats.points > 0)
            .values(points=UserStats.points - 1)
        )
        await session.commit()
        return deduction.rowcount == 1
