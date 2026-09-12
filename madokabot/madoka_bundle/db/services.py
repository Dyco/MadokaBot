from sqlalchemy.ext.asyncio import AsyncSession

from .models import SignRecord, UserStats


class UserService:
    """用户数据服务：只读取已注册用户，不再隐式创建账号。"""

    @staticmethod
    async def get_user_data(
        session: AsyncSession,
        uid: str,
    ) -> tuple[UserStats, SignRecord]:
        """获取已注册用户的核心数据。"""
        user = await session.get(UserStats, uid)
        sign = await session.get(SignRecord, uid)
        if user is None or sign is None:
            raise LookupError("用户未注册")
        return user, sign
