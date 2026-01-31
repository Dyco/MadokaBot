from sqlalchemy import select
from nonebot_plugin_datastore import create_session
from .models import UserStats, UserInventory, ShopItem, UserSkin
from ..registry import SKIN_MAP, DEFAULT_SKIN

class UserAccount:
    """用户账务处理类"""
    
    @staticmethod
    async def add_points(uid: str, amount: int):
        """增加积分"""
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                user = UserStats(user_id=uid, points=0)
                session.add(user)
            
            user.points += amount
            await session.commit()
            return user.points

    @staticmethod
    async def spend_points(uid: str, amount: int) -> bool:
        """扣除积分，余额不足返回False"""
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user or user.points < amount:
                return False
            
            user.points -= amount
            await session.commit()
            return True

    @staticmethod
    async def give_item(uid: str, item_id: int, count: int = 1):
        """发放商品到背包"""
        async with create_session() as session:
            stmt = select(UserInventory).where(
                UserInventory.user_id == uid, 
                UserInventory.item_id == item_id
            )
            inv = (await session.execute(stmt)).scalar_one_or_none()
            
            if inv:
                inv.count += count
            else:
                inv = UserInventory(user_id=uid, item_id=item_id, count=count)
                session.add(inv)
            await session.commit()
            
    @staticmethod
    async def set_skin(uid: str, skin_key: str) -> bool:
        """
        设置皮肤相关
        """
        # 资源层校验
        if skin_key not in SKIN_MAP:                                                                
            return False

        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                return False

            # 已是当前皮肤
            if user.skin_key == skin_key:
                return True

            # 仓库校验
            stmt = select(UserSkin).where(
                UserSkin.user_id == uid,
                UserSkin.skin_key == skin_key
            )
            owned = (await session.execute(stmt)).scalar_one_or_none()
            if not owned:
                return False

            user.skin_key = skin_key
            await session.commit()
        return True
    
    @staticmethod
    async def get_current_skin(uid: str) -> str:
        """
        获取用户当前皮肤
        - 用户不存在 / 数据异常 → 返回默认皮肤
        - 皮肤不存在于资源 → 返回默认皮肤
        """
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user or not user.skin_key:
                return DEFAULT_SKIN

            if user.skin_key not in SKIN_MAP:
                return DEFAULT_SKIN

            return user.skin_key
    
    
    #添加皮肤库存
    @staticmethod
    async def add_skin(uid: str, skin_key: str) -> bool:
        """
        给用户添加一个皮肤（仅库存）
        """
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                return False

            stmt = select(UserSkin).where(
                UserSkin.user_id == uid,
                UserSkin.skin_key == skin_key
            )
            exists = (await session.execute(stmt)).scalar_one_or_none()
            if exists:
                return False

            session.add(UserSkin(
                user_id=uid,
                skin_key=skin_key
            ))

            await session.commit()
            return True