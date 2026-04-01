from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from nonebot_plugin_datastore import create_session
from .models import UserStats, UserInventory, ShopItem, UserSkin
from ..registry import SKIN_MAP, DEFAULT_SKIN, SKIN_PRICE_MAP

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
    async def get_points(uid: str) -> int:
        """获取用户当前积分，不存在时返回0"""
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                return 0
            return user.points

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

    @staticmethod
    async def buy_skin(uid: str, skin_key: str) -> tuple[bool, str]:
        """
        购买皮肤：
        - 资源不存在
        - 已拥有
        - 余额不足
        """
        if skin_key not in SKIN_MAP:
            return False, "皮肤不存在"

        skin_cost = SKIN_PRICE_MAP.get(skin_key, 0)
        async with create_session() as session:
            stmt = (
                select(UserStats)
                .where(UserStats.user_id == uid)
                .with_for_update()
            )
            user = (await session.execute(stmt)).scalar_one_or_none()
            if not user:
                return False, "请先签到后再购买皮肤"

            owned_stmt = select(UserSkin).where(
                UserSkin.user_id == uid,
                UserSkin.skin_key == skin_key
            )
            owned = (await session.execute(owned_stmt)).scalar_one_or_none()
            if owned:
                return False, "你已经拥有这个皮肤"

            if user.points < skin_cost:
                return False, f"积分不足，购买 {skin_key} 需要 {skin_cost} 积分，你当前有 {user.points} 积分"

            points_stmt = (
                update(UserStats)
                .where(
                    UserStats.user_id == uid,
                    UserStats.points >= skin_cost
                )
                .values(points=UserStats.points - skin_cost)
                .returning(UserStats.points)
            )
            remain_points = (await session.execute(points_stmt)).scalar_one_or_none()
            if remain_points is None:
                current_points = (await session.get(UserStats, uid)).points if user else 0
                return False, f"积分不足，购买 {skin_key} 需要 {skin_cost} 积分，你当前有 {current_points} 积分"

            session.add(UserSkin(user_id=uid, skin_key=skin_key))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, "你已经拥有这个皮肤"

            return True, f"购买成功：{skin_key}，消耗 {skin_cost} 积分，剩余 {remain_points} 积分"
