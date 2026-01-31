from typing import Type, TypeVar, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import UserStats, SignRecord, UserSkin

T = TypeVar("T")

class UserService:
    """用户数据服务：负责聚合各种基础表的获取与初始化"""
    
    @staticmethod   
    async def get_user_data(session: AsyncSession, uid: str) -> Tuple[UserStats, SignRecord]:
        """获取并初始化用户核心数据"""
        user = await get_or_create(session, UserStats, user_id=uid)
        sign = await get_or_create(session, SignRecord, user_id=uid)
        await get_or_create(session, UserSkin, user_id=uid, skin_key=user.skin_key)
        return user, sign
    
    
async def get_or_create(session: AsyncSession, model: Type[T], **kwargs) -> T:
    """通用获取或创建逻辑，共享外部 session"""
    stmt = select(model).filter_by(**kwargs)
    result = await session.execute(stmt)
    obj = result.scalar_one_or_none()

    if obj is None:
        obj = model(**kwargs)
        session.add(obj)
        await session.flush()
    return obj
