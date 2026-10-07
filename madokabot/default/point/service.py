"""积分转账的事务处理与排名查询。"""

from nonebot_plugin_datastore import create_session
from sqlalchemy import func, select, update

from madokabot.core.user.models import UserStats


async def get_points_ranking(
    member_ids: list[str] | None = None,
) -> list[tuple[str, str, int]]:
    """积分排名查询方法。"""
    statement = select(
        UserStats.user_id,
        func.coalesce(
            func.nullif(UserStats.display_name, ""), UserStats.qq_nickname
        ),
        UserStats.points,
    )
    if member_ids is not None:
        statement = statement.where(UserStats.user_id.in_(member_ids))
    statement = statement.order_by(UserStats.points.desc(), UserStats.user_id).limit(20)
    async with create_session() as session:
        result = await session.execute(statement)
        return list(result.tuples().all())


async def transfer_points(
    sender_id: str, recipient_id: str, amount: int, recipient_name: str = ""
) -> tuple[bool, str]:
    """转账方法。"""
    if type(amount) is not int or amount <= 0:
        return False, "转账积分数量必须是正整数"
    if sender_id == recipient_id:
        return False, "不能向自己转账"

    async with create_session() as session:
        recipient = await session.scalar(
            select(UserStats.qq_nickname).where(UserStats.user_id == recipient_id)
        )
        if recipient is None:
            return False, "收款人尚未注册，请对方先发送“注册”"

        deduction = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == sender_id, UserStats.points >= amount)
            .values(points=UserStats.points - amount)
        )
        if deduction.rowcount != 1:
            await session.rollback()
            balance = await session.scalar(
                select(UserStats.points).where(UserStats.user_id == sender_id)
            )
            if balance is None:
                return False, "请先发送“注册”完成用户注册"
            return False, f"积分不足，转账需要{amount}积分，你当前只有{balance}积分"

        credit = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == recipient_id)
            .values(points=UserStats.points + amount)
        )
        if credit.rowcount != 1:
            await session.rollback()
            return False, "收款人账号发生变化，请重新转账"

        remaining_points = await session.scalar(
            select(UserStats.points).where(UserStats.user_id == sender_id)
        )
        await session.commit()
        name = recipient_name.strip() or recipient.strip() or f"QQ{recipient_id}"
        return True, (
            f"转账成功：向{name}转账{amount}积分，个人剩余{remaining_points}积分"
        )
