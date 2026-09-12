from datetime import datetime
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import fullmatch
from nonebot_plugin_datastore import create_session

from ...db.models import SignRecord, UserInventory, UserStats
from ...registry import SKIN_SHOP
from .config import config


_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


register_matcher = on_message(
    rule=fullmatch(config.register_keywords),
    priority=10,
    block=True,
)


async def register_user(
    session: AsyncSession,
    uid: str,
) -> tuple[UserStats, SignRecord, bool]:
    """Create all user state in one place and return whether it was newly created."""
    user = await session.get(UserStats, uid)
    if user is not None:
        sign = await session.get(SignRecord, uid)
        if sign is None:
            sign = SignRecord(
                user_id=uid,
                last_sign_date=None,
                continuous_days=0,
                total_count=0,
            )
            session.add(sign)
            try:
                await session.commit()
            except IntegrityError:
                # Another request may have repaired the same partial account.
                await session.rollback()
                sign = await session.get(SignRecord, uid)
                if sign is None:
                    raise
                user = await session.get(UserStats, uid)
            else:
                await session.refresh(user)
                await session.refresh(sign)
        return user, sign, False

    user = UserStats(
        user_id=uid,
        register_time=datetime.now(_SHANGHAI_TZ),
        points=0,
        favorability=0,
        skin_asset=config.initial_chara,
    )
    sign = SignRecord(
        user_id=uid,
        last_sign_date=None,
        continuous_days=0,
        total_count=0,
    )
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
        # A registration command and a sign command may arrive together.
        await session.rollback()
        existing_user = await session.get(UserStats, uid)
        existing_sign = await session.get(SignRecord, uid)
        if existing_user is None or existing_sign is None:
            raise
        return existing_user, existing_sign, False

    await session.refresh(user)
    await session.refresh(sign)
    return user, sign, True


async def get_or_register_user(
    session: AsyncSession,
    uid: str,
) -> tuple[UserStats, SignRecord, bool]:
    """Return an existing account or create it through the common flow."""
    user = await session.get(UserStats, uid)
    sign = await session.get(SignRecord, uid) if user is not None else None
    if user is not None and sign is not None:
        return user, sign, False
    return await register_user(session, uid)


@register_matcher.handle()
async def _register(event: MessageEvent):
    async with create_session() as session:
        _, _, created = await register_user(session, event.get_user_id())

    if created:
        await register_matcher.finish("注册成功，已发放默认立绘。")
    await register_matcher.finish("你已经注册过了。")
