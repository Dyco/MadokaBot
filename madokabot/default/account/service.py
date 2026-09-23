from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from nonebot_plugin_datastore import create_session

from madokabot.core.user.models import SignRecord, UserStats
from madokabot.default.shop.models import UserInventory
from madokabot.default.shop.catalog import SKIN_SHOP
from .config import config

RENAME_COST = 10
DISPLAY_NAME_MAX_LENGTH = 10


async def rename_user(uid: str, name: str) -> tuple[bool, str]:
    """校验显示名，并在余额足够时原子扣费、保存新名字。"""
    name = name.strip()
    if not name or len(name) > DISPLAY_NAME_MAX_LENGTH:
        return False, f"名字长度须为 1～{DISPLAY_NAME_MAX_LENGTH} 个字符或汉字"

    async with create_session() as session:
        result = await session.execute(
            update(UserStats)
            .where(UserStats.user_id == uid, UserStats.points >= RENAME_COST)
            .values(display_name=name, points=UserStats.points - RENAME_COST)
        )
        if result.rowcount != 1:
            registered = await session.scalar(
                select(UserStats.user_id).where(UserStats.user_id == uid)
            )
            if registered is None:
                return False, "请先发送“注册”完成用户注册"
            return False, f"积分不足，改名需要 {RENAME_COST} 积分"

        remaining_points = await session.scalar(
            select(UserStats.points).where(UserStats.user_id == uid)
        )
        await session.commit()
        return True, (
            f"改名成功：{name}，消耗 {RENAME_COST} 积分，剩余 {remaining_points} 积分"
        )


async def register_user(
    session: AsyncSession,
    uid: str,
    qq_nickname: str = "",
) -> tuple[UserStats, SignRecord, bool]:
    """集中创建用户数据，并返回本次是否为首次注册。"""
    normalized_nickname = qq_nickname.strip()
    user = await session.get(UserStats, uid)
    if user is not None:
        if normalized_nickname and user.qq_nickname != normalized_nickname:
            user.qq_nickname = normalized_nickname
            await session.commit()
            # 提交会使用户属性过期，后续签到及会话外渲染仍需读取这些属性。
            await session.refresh(user)
        sign = await session.get(SignRecord, uid)
        if sign is None:
            sign = SignRecord(user_id=uid)
            session.add(sign)
            try:
                await session.commit()
            except IntegrityError:
                # 并发请求可能已补全同一份不完整账号。
                await session.rollback()
                sign = await session.get(SignRecord, uid)
                user = await session.get(UserStats, uid)
                if user is None or sign is None:
                    raise
            else:
                await session.refresh(user)
                await session.refresh(sign)
        return user, sign, False

    user = UserStats(
        user_id=uid,
        qq_nickname=normalized_nickname,
        skin_asset=config.initial_chara,
    )
    sign = SignRecord(user_id=uid)
    session.add_all([user, sign])
    if config.initial_chara:
        session.add(
            UserInventory(
                user_id=uid,
                resource_type=SKIN_SHOP.type.name,
                content=SKIN_SHOP.content.name,
                file_name=config.initial_chara,
                quantity=1,
            )
        )

    try:
        await session.commit()
    except IntegrityError:
        # 注册与签到可能同时创建同一账号。
        await session.rollback()
        existing_user = await session.get(UserStats, uid)
        existing_sign = await session.get(SignRecord, uid)
        if existing_user is None or existing_sign is None:
            raise
        return existing_user, existing_sign, False

    await session.refresh(user)
    await session.refresh(sign)
    return user, sign, True
