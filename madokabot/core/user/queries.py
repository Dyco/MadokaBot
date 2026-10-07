from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SignRecord, UserStats


class UserQueries:
    """用户数据查询。"""

    @staticmethod
    async def get_points_ranking(
        session: AsyncSession,
    ) -> list[tuple[str, str, int, int]]:
        """积分排名查询方法。"""
        points = await session.execute(
            select(
                UserStats.user_id,
                func.coalesce(
                    func.nullif(UserStats.display_name, ""), UserStats.qq_nickname
                ),
                UserStats.points,
                func.coalesce(SignRecord.total_count, 0),
            )
            .outerjoin(SignRecord, SignRecord.user_id == UserStats.user_id)
            .order_by(UserStats.points.desc(), UserStats.user_id)
            .limit(5)
        )
        return list(points.tuples().all())

    @staticmethod
    async def get_user_data(
        session: AsyncSession,
        uid: str,
    ) -> tuple[UserStats, SignRecord]:
        """用户数据查询方法。"""
        user = await session.get(UserStats, uid)
        sign = await session.get(SignRecord, uid)
        if user is None or sign is None:
            raise LookupError("用户未注册")
        return user, sign
