from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SignRecord, UserStats
from .ranking import get_ranking_superusers

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class UserQueries:
    """用户数据查询。"""

    @staticmethod
    async def get_daily_sign_order(
        session: AsyncSession,
        sign: SignRecord,
        now: datetime,
    ) -> int | None:
        """按上海日期和签到时间查询当日全局顺序，同一时间按用户编号排序。"""
        if sign.last_sign_date is None:
            return None
        signed_at = sign.last_sign_date
        if signed_at.tzinfo is not None:
            signed_at = signed_at.astimezone(_SHANGHAI_TZ).replace(tzinfo=None)
        today = now.astimezone(_SHANGHAI_TZ).date()
        if signed_at.date() != today:
            return None
        day_start = datetime.combine(today, time.min)
        return await session.scalar(
            select(func.count())
            .select_from(SignRecord)
            .where(
                SignRecord.last_sign_date >= day_start,
                SignRecord.last_sign_date < day_start + timedelta(days=1),
                or_(
                    SignRecord.last_sign_date < signed_at,
                    and_(
                        SignRecord.last_sign_date == signed_at,
                        SignRecord.user_id <= sign.user_id,
                    ),
                ),
            )
        )

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
            .where(UserStats.user_id.not_in(get_ranking_superusers()))
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
