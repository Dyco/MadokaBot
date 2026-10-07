"""用户基础资料服务。"""

from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserProfile


async def ensure_user_profile(
    session: AsyncSession, user_id: str, qq_nickname: str = ""
) -> UserProfile:
    """用户资料补齐方法。"""
    profile = await session.get(UserProfile, user_id)
    nickname = qq_nickname.strip()[:64]
    if profile is None:
        profile = UserProfile(user_id=user_id, qq_nickname=nickname)
        session.add(profile)
    elif nickname:
        profile.qq_nickname = nickname
    return profile
