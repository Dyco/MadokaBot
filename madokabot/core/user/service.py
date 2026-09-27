"""不改变积分账号注册状态的基础用户资料操作。"""

from sqlalchemy.ext.asyncio import AsyncSession

from .models import UserProfile


async def ensure_user_profile(
    session: AsyncSession, user_id: str, qq_nickname: str = ""
) -> UserProfile:
    """在当前事务中按需创建基础资料，并更新非空 QQ 昵称。"""
    profile = await session.get(UserProfile, user_id)
    nickname = qq_nickname.strip()[:64]
    if profile is None:
        profile = UserProfile(user_id=user_id, qq_nickname=nickname)
        session.add(profile)
    elif nickname:
        profile.qq_nickname = nickname
    return profile
