from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot_plugin_datastore import create_session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import SignRecord, UserInventory, UserStats
from ...registry import SKIN_SHOP
from .config import config
from .matchers import register_cmd


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


@register_cmd.handle()
async def _register(event: MessageEvent):
    nickname = event.sender.nickname or event.sender.card or ""
    async with create_session() as session:
        _, _, created = await register_user(
            session,
            event.get_user_id(),
            nickname,
        )

    if created:
        await register_cmd.finish("事务所信息注册成功。")
    await register_cmd.finish("制作人，你已经注册过了事务所信息了。")
