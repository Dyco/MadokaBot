from typing import Any

from sqlalchemy import select

from nonebot_plugin_datastore import create_session

from .models import ShopItem, UserInventory, UserSkin, UserStats
from ..registry import DEFAULT_SKIN, SKIN_MAP, SKIN_PRICE_MAP


class UserAccount:
    @staticmethod
    async def add_points(uid: str, amount: int):
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
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user or user.points < amount:
                return False

            user.points -= amount
            await session.commit()
            return True

    @staticmethod
    async def get_points(uid: str) -> int:
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                return 0
            return user.points

    @staticmethod
    async def give_item(uid: str, item_id: int, count: int = 1):
        async with create_session() as session:
            stmt = select(UserInventory).where(
                UserInventory.user_id == uid,
                UserInventory.item_id == item_id,
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
        if skin_key not in SKIN_MAP:
            return False

        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                return False

            if user.skin_key == skin_key:
                return True

            stmt = select(UserSkin).where(
                UserSkin.user_id == uid,
                UserSkin.skin_key == skin_key,
            )
            owned = (await session.execute(stmt)).scalar_one_or_none()
            if not owned:
                return False

            user.skin_key = skin_key
            await session.commit()
        return True

    @staticmethod
    async def get_current_skin(uid: str) -> str:
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user or not user.skin_key:
                return DEFAULT_SKIN

            if user.skin_key not in SKIN_MAP:
                return DEFAULT_SKIN

            return user.skin_key

    @staticmethod
    async def add_skin(uid: str, skin_key: str) -> bool:
        async with create_session() as session:
            user = await session.get(UserStats, uid)
            if not user:
                return False

            stmt = select(UserSkin).where(
                UserSkin.user_id == uid,
                UserSkin.skin_key == skin_key,
            )
            exists = (await session.execute(stmt)).scalar_one_or_none()
            if exists:
                return False

            session.add(UserSkin(user_id=uid, skin_key=skin_key))
            await session.commit()
            return True

    @staticmethod
    async def sync_shop_skins() -> None:
        async with create_session() as session:
            existing_items = (
                await session.execute(select(ShopItem).where(ShopItem.item_type == "skin"))
            ).scalars().all()
            existing_by_key = {item.item_key: item for item in existing_items}

            for skin_key, path in SKIN_MAP.items():
                item = existing_by_key.get(skin_key)
                if item is None:
                    session.add(
                        ShopItem(
                            item_key=skin_key,
                            name=path.stem,
                            item_type="skin",
                            asset_name=path.name,
                            price=SKIN_PRICE_MAP.get(skin_key, 0),
                            description=f"立绘：{path.name}",
                            is_active=1,
                        )
                    )
                    continue

                item.name = path.stem
                item.asset_name = path.name
                item.price = SKIN_PRICE_MAP.get(skin_key, item.price)
                item.item_type = "skin"
                item.description = f"立绘：{path.name}"
                item.is_active = 1

            for item in existing_items:
                if item.item_key not in SKIN_MAP:
                    item.is_active = 0

            await session.commit()

    @staticmethod
    async def get_shop_skin_list(uid: str) -> list[dict[str, Any]]:
        async with create_session() as session:
            items = (
                await session.execute(
                    select(ShopItem)
                    .where(ShopItem.item_type == "skin", ShopItem.is_active == 1)
                    .order_by(ShopItem.item_id.asc())
                )
            ).scalars().all()

            owned_skin_keys = set(
                (
                    await session.execute(
                        select(UserSkin.skin_key).where(UserSkin.user_id == uid)
                    )
                ).scalars().all()
            )

            result: list[dict[str, Any]] = []
            for item in items:
                result.append(
                    {
                        "item_id": item.item_id,
                        "item_key": item.item_key,
                        "asset_name": item.asset_name,
                        "price": item.price,
                        "owned": item.item_key in owned_skin_keys,
                    }
                )
            return result

    @staticmethod
    async def buy_shop_item(uid: str, item_id: int) -> tuple[bool, str]:
        async with create_session() as session:
            item = await session.get(ShopItem, item_id)
            if not item or item.item_type != "skin" or item.is_active != 1:
                return False, "该商品不存在或当前不可购买"

            if item.item_key not in SKIN_MAP:
                item.is_active = 0
                await session.commit()
                return False, "该商品资源已失效，已自动下架"

            user = await session.get(UserStats, uid)
            if not user:
                return False, "请先签到后再购买商品"

            owned = (
                await session.execute(
                    select(UserSkin).where(
                        UserSkin.user_id == uid,
                        UserSkin.skin_key == item.item_key,
                    )
                )
            ).scalar_one_or_none()
            if owned:
                return False, "你已经拥有这个立绘了"

            if user.points < item.price:
                return (
                    False,
                    f"积分不足，购买 {item.asset_name} 需要 {item.price} 积分，你当前只有 {user.points} 积分",
                )

            user.points -= item.price
            session.add(UserSkin(user_id=uid, skin_key=item.item_key))
            await session.commit()
            return (
                True,
                f"购买成功：{item.asset_name}，消耗 {item.price} 积分，剩余 {user.points} 积分",
            )
