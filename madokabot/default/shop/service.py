"""立绘与签到模板的库存、购买和切换服务。"""

from pathlib import Path
from typing import Any

from sqlalchemy import exists, insert, literal, select, update
from sqlalchemy.exc import IntegrityError
from nonebot_plugin_datastore import create_session

from madokabot.core.user.models import UserStats
from .models import UserInventory
from .catalog import (
    DEFAULT_SIGN_ASSET,
    SIGN_SHOP,
    SIGN_TEMPLATES,
    SKIN_SHOP,
    ShopDefinition,
    get_sign_map,
    get_skin_map,
)


def _inventory_conditions(uid: str, shop: ShopDefinition) -> tuple:
    """保留原有资源分类键，统一筛选该用户的库存。"""
    return (
        UserInventory.user_id == uid,
        UserInventory.resource_type == shop.type.name,
        UserInventory.content == shop.content.name,
        UserInventory.quantity > 0,
    )


async def grant_default_sign_templates() -> None:
    """启动时向旧账号补发免费模板，重复启动不增加数量或覆盖已选模板。"""
    async with create_session() as session:
        default_conditions = (
            UserInventory.resource_type == SIGN_SHOP.type.name,
            UserInventory.content == SIGN_SHOP.content.name,
            UserInventory.file_name == DEFAULT_SIGN_ASSET,
        )
        await session.execute(update(UserInventory).where(
            *default_conditions, UserInventory.quantity <= 0,
        ).values(quantity=1))
        missing = select(
            UserStats.user_id, literal(SIGN_SHOP.type.name),
            literal(SIGN_SHOP.content.name), literal(DEFAULT_SIGN_ASSET), literal(1),
        ).where(~exists().where(
            UserInventory.user_id == UserStats.user_id, *default_conditions,
        ))
        await session.execute(insert(UserInventory).from_select(
            ["user_id", "type", "content", "file_name", "quantity"], missing,
        ))
        await session.commit()


async def _get_shop_items(
    uid: str, shop: ShopDefinition, entries: dict[str, Path],
) -> list[dict[str, Any]]:
    """读取商品、价格、持有状态和当前选择。"""
    async with create_session() as session:
        user = await session.get(UserStats, uid)
        if user is None:
            raise LookupError("用户未注册")
        owned = set((await session.scalars(
            select(UserInventory.file_name).where(*_inventory_conditions(uid, shop))
        )).all())
        current = user.sign_template if shop == SIGN_SHOP else user.skin_asset
        return [
            {
                "item_key": key,
                "asset_name": path.name,
                "name": SIGN_TEMPLATES[key][1] if shop == SIGN_SHOP else path.stem,
                "price": SIGN_TEMPLATES[key][2] if shop == SIGN_SHOP else shop.price,
                "owned": path.name in owned,
                "current": (
                    path.with_suffix(".html").name if shop == SIGN_SHOP else path.name
                ) == current,
            }
            for key, path in entries.items()
        ]


async def _switch_item(
    uid: str, key: str, shop: ShopDefinition, entries: dict[str, Path],
) -> tuple[bool, str]:
    """只有库存中持有且资源仍可用的商品才能切换。"""
    key = key.strip().lower()
    label = "签到模板" if shop == SIGN_SHOP else "立绘"
    path = entries.get(key)
    if path is None:
        return False, f"该{label}不存在"
    async with create_session() as session:
        user = await session.get(UserStats, uid)
        if user is None:
            return False, "请先发送“注册”完成用户注册"
        owned = await session.scalar(select(UserInventory.file_name).where(
            *_inventory_conditions(uid, shop), UserInventory.file_name == path.name,
        ))
        if owned is None:
            return False, f"你还没有这个{label}，请先在商店购买"
        attribute = "sign_template" if shop == SIGN_SHOP else "skin_asset"
        selection = path.with_suffix(".html").name if shop == SIGN_SHOP else path.name
        if getattr(user, attribute) == selection:
            return True, f"当前已经在使用 {key}"
        setattr(user, attribute, selection)
        await session.commit()
        return True, f"{label}切换成功：{key}（{path.stem}）"


async def _buy_item(
    uid: str, key: str, shop: ShopDefinition, entries: dict[str, Path],
) -> tuple[bool, str]:
    """原子扣款并写入库存，重复或并发购买失败时整笔回滚。"""
    key = key.strip().lower()
    path = entries.get(key)
    if path is None:
        return False, "该商品不存在或当前不可购买"
    label = "签到模板" if shop == SIGN_SHOP else "立绘"
    price = SIGN_TEMPLATES[key][2] if shop == SIGN_SHOP else shop.price
    async with create_session() as session:
        points = await session.scalar(
            select(UserStats.points).where(UserStats.user_id == uid)
        )
        if points is None:
            return False, "请先发送“注册”完成用户注册"
        owned = await session.scalar(select(UserInventory.file_name).where(
            *_inventory_conditions(uid, shop), UserInventory.file_name == path.name,
        ))
        if owned is not None:
            return False, f"你已经拥有这个{label}了"
        if points < price:
            return False, f"积分不足，购买 {key} 需要 {price} 积分，你当前只有 {points} 积分"
        deduction = await session.execute(update(UserStats).where(
            UserStats.user_id == uid, UserStats.points >= price,
        ).values(points=UserStats.points - price))
        if deduction.rowcount != 1:
            await session.rollback()
            return False, "积分余额发生变化，请重新购买"
        try:
            inventory = await session.get(
                UserInventory, (uid, shop.type.name, shop.content.name, path.name)
            )
            if inventory is not None:
                # 并发购买者可能在扣款等待期间已写入库存，需撤销本次扣款。
                if inventory.quantity > 0:
                    await session.rollback()
                    return False, f"你已经拥有这个{label}了"
                inventory.quantity = 1
            else:
                session.add(UserInventory(
                    user_id=uid, resource_type=shop.type.name, content=shop.content.name,
                    file_name=path.name, quantity=1,
                ))
            await session.flush()
            remaining = await session.scalar(
                select(UserStats.points).where(UserStats.user_id == uid)
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False, f"你已经拥有这个{label}了"
        return True, (
            f"购买成功：{path.name}（{key}），消耗 {price} 积分，剩余 {remaining} 积分。"
            f"使用“设置 {label} {key}”即可切换"
        )


class SkinService:
    """处理立绘商品、库存和当前立绘。"""

    @staticmethod
    async def switch_skin(uid: str, skin_key: str) -> tuple[bool, str]:
        """切换已持有立绘。"""
        return await _switch_item(uid, skin_key, SKIN_SHOP, get_skin_map())

    @staticmethod
    async def get_shop_skin_list(uid: str) -> list[dict[str, Any]]:
        """列出立绘商品。"""
        return await _get_shop_items(uid, SKIN_SHOP, get_skin_map())

    @staticmethod
    async def get_owned_skin_list(uid: str) -> list[dict[str, Any]]:
        """列出可用的已持有立绘。"""
        return [item for item in await SkinService.get_shop_skin_list(uid) if item["owned"]]

    @staticmethod
    async def buy_shop_skin(uid: str, skin_key: str) -> tuple[bool, str]:
        """仅按带 skin 前缀的商品编号购买立绘。"""
        return await _buy_item(uid, skin_key, SKIN_SHOP, get_skin_map())


class SignTemplateService:
    """处理签到模板商品、库存和当前模板。"""

    @staticmethod
    async def get_shop_template_list(uid: str) -> list[dict[str, Any]]:
        """列出具有完整资源的模板商品。"""
        return await _get_shop_items(uid, SIGN_SHOP, get_sign_map())

    @staticmethod
    async def get_owned_template_list(uid: str) -> list[dict[str, Any]]:
        """列出库存中持有的模板。"""
        return [item for item in await SignTemplateService.get_shop_template_list(uid) if item["owned"]]

    @staticmethod
    async def buy_template(uid: str, key: str) -> tuple[bool, str]:
        """按固定商品编号购买签到模板。"""
        return await _buy_item(uid, key, SIGN_SHOP, get_sign_map())

    @staticmethod
    async def switch_template(uid: str, key: str) -> tuple[bool, str]:
        """切换库存中持有的签到模板。"""
        return await _switch_item(uid, key, SIGN_SHOP, get_sign_map())
