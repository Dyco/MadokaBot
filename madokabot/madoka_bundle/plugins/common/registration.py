from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import fullmatch
from nonebot_plugin_datastore import create_session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import SignRecord, UserInventory, UserStats
from ...registry import SKIN_SHOP
from .config import config


register_matcher = on_message(
    rule=fullmatch(config.register_keywords),
    priority=10,
    block=True,
)


async def register_user(
    session: AsyncSession,
    uid: str,
) -> tuple[UserStats, SignRecord, bool]:
    """集中创建用户数据，并返回本次是否为首次注册。"""
    user = await session.get(UserStats, uid)
    if user is not None:
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


@register_matcher.handle()
async def _register(event: MessageEvent):
    async with create_session() as session:
        _, _, created = await register_user(session, event.get_user_id())

    if created:
        await register_matcher.finish("注册成功，已发放默认立绘。")
    await register_matcher.finish("你已经注册过了。")
