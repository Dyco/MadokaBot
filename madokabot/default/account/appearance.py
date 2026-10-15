"""账号随机立绘与模板设置。"""

from pathlib import Path
from random import choice
from typing import Literal

from nonebot_plugin_datastore import create_session
from sqlalchemy import update

from madokabot.core.user.models import UserStats
from madokabot.default.shop.catalog import DEFAULT_SIGN_ASSET
from madokabot.default.shop.service import SignTemplateService, SkinService

from .config import config


async def _get_random_assets(uid: str, category: Literal["skin", "template"]) -> list[str]:
    """非默认库存查询方法。"""
    if category == "skin":
        items = await SkinService.get_owned_skin_list(uid)
        default_asset = config.initial_chara
    else:
        items = await SignTemplateService.get_owned_template_list(uid)
        default_asset = DEFAULT_SIGN_ASSET
    return [item["asset_name"] for item in items if item["asset_name"] != default_asset]


async def toggle_random_appearance(uid: str, category: Literal["skin", "template"]) -> tuple[bool, str]:
    """随机外观开关方法。"""
    column = UserStats.random_skin if category == "skin" else UserStats.random_template
    label = "立绘" if category == "skin" else "模板"
    async with create_session() as session:
        user = await session.get(UserStats, uid)
        if user is None:
            return False, "请先发送“注册”完成用户注册"
        if not getattr(user, column.key) and not await _get_random_assets(uid, category):
            return False, f"你还没有可用的非默认{label}，请先在商店购买"
        enabled = await session.scalar(
            update(UserStats).where(UserStats.user_id == uid)
            .values({column: ~column}).returning(column)
        )
        await session.commit()
    if enabled:
        return True, f"随机{label}已开启，每次展示将从库存中随机使用非默认{label}"
    return True, f"随机{label}已关闭，恢复使用手动选择的{label}"


async def select_skin_asset(user: UserStats) -> str:
    """展示立绘选择方法。"""
    if user.random_skin:
        assets = await _get_random_assets(user.user_id, "skin")
        if assets:
            return choice(assets)
    return user.skin_asset


async def select_sign_template(user: UserStats) -> str:
    """展示模板选择方法。"""
    if user.random_template:
        assets = await _get_random_assets(user.user_id, "template")
        if assets:
            return Path(choice(assets)).with_suffix(".html").name
    return user.sign_template
