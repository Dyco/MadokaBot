import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from madokabot.core.user.models import SignRecord, UserStats

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def calculate_reward(continuous_days: int) -> tuple[int, int, int]:
    """签到奖励计算方法。"""
    bonus_points = min(max(continuous_days - 1, 0), 10)
    base_points = random.randint(3, 6)
    reward_favor = random.randint(0, 1)
    return base_points, bonus_points, reward_favor


def can_sign_today(sign: SignRecord) -> bool:
    """判断用户今天是否尚未签到。"""
    if sign.last_sign_date is None:
        return True
    return sign.last_sign_date.date() != datetime.now(_SHANGHAI_TZ).date()


async def execute_sign_update(
    user: UserStats,
    sign: SignRecord,
    session: AsyncSession,
) -> dict[str, int]:
    """签到数据更新方法。"""
    now = datetime.now(_SHANGHAI_TZ)
    today = now.date()
    last_date = sign.last_sign_date.date() if sign.last_sign_date else None

    if last_date == today - timedelta(days=1):
        sign.continuous_days += 1
    else:
        sign.continuous_days = 1

    base_points, bonus_points, reward_favor = calculate_reward(sign.continuous_days)
    # 原子增减积分，避免并发更新覆盖余额。
    await session.execute(
        update(UserStats)
        .where(UserStats.user_id == user.user_id)
        .values(points=UserStats.points + base_points + bonus_points)
    )
    user.favorability += reward_favor
    sign.total_count += 1
    sign.last_sign_date = now

    await session.commit()
    return {
        "reward_points": base_points,
        "bonus_point": bonus_points,
        "reward_favor": reward_favor,
    }
