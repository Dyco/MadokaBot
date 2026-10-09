"""跨业务共享的账号查询接口。"""

from nonebot_plugin_datastore import create_session
from sqlalchemy import func, select

from .models import UserStats
from .ranking import get_ranking_superusers


class UserAccount:
    """不依赖业务插件的账号与积分查询。"""

    @staticmethod
    async def get_points(uid: str) -> int:
        """读取已注册用户的积分。"""
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if user is None:
                raise LookupError("用户未注册")
            return user.points

    @staticmethod
    async def get_points_and_rank(uid: str) -> tuple[int, int | None]:
        """积分与总排名查询方法。"""
        ranking = select(
            UserStats.user_id,
            UserStats.points,
            func.row_number().over(
                order_by=(UserStats.points.desc(), UserStats.user_id)
            ).label("rank"),
        ).where(UserStats.user_id.not_in(get_ranking_superusers())).subquery()
        async with create_session() as session:
            result = await session.execute(
                select(UserStats.points, ranking.c.rank)
                .outerjoin(ranking, ranking.c.user_id == UserStats.user_id)
                .where(UserStats.user_id == uid)
            )
            row = result.one_or_none()
            if row is None:
                raise LookupError("用户未注册")
            return row.points, row.rank

    @staticmethod
    async def is_registered(uid: str) -> bool:
        """判断用户是否已注册。"""
        async with create_session() as session:
            return await session.get(UserStats, uid) is not None
