"""跨业务共享的账号查询接口。"""

from nonebot_plugin_datastore import create_session

from .models import UserStats


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
    async def is_registered(uid: str) -> bool:
        """判断用户是否已注册。"""
        async with create_session() as session:
            return await session.get(UserStats, uid) is not None
