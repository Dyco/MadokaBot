"""超级用户账号修改服务。"""

from typing import Literal

from nonebot_plugin_datastore import create_session
from sqlalchemy import update

from madokabot.core.user.models import UserStats


async def modify_all_user_points(amount: int) -> tuple[bool, str]:
    """原子增减全体已注册用户的积分，并返回涉及人数。"""
    async with create_session() as session:
        result = await session.execute(
            update(UserStats).values(points=UserStats.points + amount)
        )
        count = result.rowcount
        await session.commit()
    change = f"增加{amount}" if amount >= 0 else f"减少{-amount}"
    return True, f"修改成功：全体已注册用户（共{count}人）的积分{change}。"


async def modify_user_stat(
    uid: str, field: Literal["好感", "积分"], amount: int
) -> tuple[bool, str]:
    """用户数值修改方法。"""
    column = {"好感": UserStats.favorability, "积分": UserStats.points}[field]
    async with create_session() as session:
        result = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == uid)
            .values({column: column + amount})
            .returning(UserStats.qq_nickname, column)
        )
        row = result.one_or_none()
        if row is None:
            return False, "目标用户尚未注册，请对方先发送“注册”"
        nickname, value = row
        await session.commit()
    name = nickname.strip() or f"QQ{uid}"
    change = f"增加{amount}" if amount >= 0 else f"减少{-amount}"
    return True, f"修改成功：{name}的{field}{change}，当前{field}为{value}。"
