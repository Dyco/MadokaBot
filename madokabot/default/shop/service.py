"""立绘商店的业务服务。"""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nonebot_plugin_datastore import create_session

from madokabot.core.user.models import UserStats
from .models import UserInventory
from .catalog import SKIN_SHOP, get_skin_map


async def _get_owned_skin_names(session: AsyncSession, uid: str) -> set[str]:
    """读取当前用户实际持有的立绘文件名。"""
    result = await session.scalars(
        select(UserInventory.file_name).where(
            UserInventory.user_id == uid,
            UserInventory.resource_type == SKIN_SHOP.type.name,
            UserInventory.content == SKIN_SHOP.content.name,
            UserInventory.quantity > 0,
        )
    )
    return set(result.all())


class SkinService:
    """处理立绘库存、购买和当前立绘选择。"""

    @staticmethod
    async def switch_skin(uid: str, skin_key: str) -> tuple[bool, str]:
        """校验立绘持有记录并切换当前使用的立绘。"""
        normalized_key = skin_key.strip().lower()
        skin_path = get_skin_map().get(normalized_key)
        if skin_path is None:
            return False, "该立绘不存在"
        asset_name = skin_path.name

        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if user is None:
                return False, "请先发送“注册”完成用户注册"

            owned = (
                await session.execute(
                    select(UserInventory.file_name).where(
                        UserInventory.user_id == uid,
                        UserInventory.resource_type == SKIN_SHOP.type.name,
                        UserInventory.content == SKIN_SHOP.content.name,
                        UserInventory.file_name == asset_name,
                        UserInventory.quantity > 0,
                    )
                )
            ).scalar_one_or_none()
            if owned is None:
                return False, "你还没有这个立绘，请先在商店购买"

            if user.skin_asset == asset_name:
                return True, f"当前已经在使用 {normalized_key}"

            user.skin_asset = asset_name
            await session.commit()
            return True, f"立绘切换成功：{normalized_key}（{skin_path.stem}）"

    @staticmethod
    async def get_shop_skin_list(uid: str) -> list[dict[str, Any]]:
        """列出立绘商品及当前用户的持有状态。"""
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if user is None:
                raise LookupError("用户未注册")
            owned_assets = await _get_owned_skin_names(session, uid)

            return [
                {
                    "display_id": display_id,
                    "item_key": skin_key,
                    "asset_name": path.name,
                    "price": SKIN_SHOP.price,
                    "owned": path.name in owned_assets,
                    "current": path.name == user.skin_asset,
                }
                for display_id, (skin_key, path) in enumerate(
                    get_skin_map().items(), start=1
                )
            ]

    @staticmethod
    async def get_owned_skin_list(uid: str) -> list[dict[str, Any]]:
        """列出用户持有且仍有资源文件的立绘。"""
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if user is None:
                raise LookupError("用户未注册")
            owned_assets = await _get_owned_skin_names(session, uid)

            return [
                {
                    "item_key": skin_key,
                    "asset_name": path.name,
                    "current": path.name == user.skin_asset,
                }
                for skin_key, path in get_skin_map().items()
                if path.name in owned_assets
            ]

    @staticmethod
    async def buy_shop_skin(uid: str, display_id: int) -> tuple[bool, str]:
        """在同一事务中扣除积分并添加立绘库存，拒绝重复购买。"""
        skin_entries = list(get_skin_map().items())
        if display_id < 1 or display_id > len(skin_entries):
            return False, "该商品不存在或当前不可购买"

        skin_key, path = skin_entries[display_id - 1]
        async with create_session() as session:
            item_asset_name = path.name
            item_price = SKIN_SHOP.price

            current_points = await session.scalar(
                select(UserStats.points).where(UserStats.user_id == uid)
            )
            if current_points is None:
                return False, "请先发送“注册”完成用户注册"

            owned = (
                await session.execute(
                    select(UserInventory).where(
                        UserInventory.user_id == uid,
                        UserInventory.resource_type == SKIN_SHOP.type.name,
                        UserInventory.content == SKIN_SHOP.content.name,
                        UserInventory.file_name == item_asset_name,
                        UserInventory.quantity > 0,
                    )
                )
            ).scalar_one_or_none()
            if owned is not None:
                return False, "你已经拥有这个立绘了"

            if current_points < item_price:
                return (
                    False,
                    f"积分不足，购买 {item_asset_name} 需要 {item_price} 积分，你当前只有 {current_points} 积分",
                )

            deduction = await session.execute(
                update(UserStats)
                .where(
                    UserStats.user_id == uid,
                    UserStats.points >= item_price,
                )
                .values(points=UserStats.points - item_price)
            )
            if deduction.rowcount != 1:
                await session.rollback()
                return False, "积分余额发生变化，请重新购买"

            try:
                session.add(
                    UserInventory(
                        user_id=uid,
                        resource_type=SKIN_SHOP.type.name,
                        content=SKIN_SHOP.content.name,
                        file_name=item_asset_name,
                        quantity=1,
                    )
                )
                await session.flush()
                remaining_points = (
                    await session.execute(
                        select(UserStats.points).where(UserStats.user_id == uid)
                    )
                ).scalar_one()
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False, "你已经拥有这个立绘了"

            return (
                True,
                f"购买成功：{item_asset_name}（{skin_key}），消耗 {item_price} 积分，"
                f"剩余 {remaining_points} 积分。使用“设置 立绘 {skin_key}”即可切换",
            )
