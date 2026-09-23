"""签到会话编排、并发控制与卡片发送。"""

import asyncio
from collections import defaultdict

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot_plugin_datastore import create_session

from madokabot.core.messaging.response import respond
from madokabot.default.account.render import render_sign_card
from madokabot.default.account.service import register_user
from .matchers import sign_matcher
from .service import can_sign_today, execute_sign_update

sign_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@sign_matcher.handle()
async def _handle_sign(bot: Bot, event: MessageEvent):
    """串行处理同一用户的签到并返回用户卡片。"""
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname or uid
    lock = sign_locks[uid]
    if lock.locked():
        return

    image_message = None
    try:
        async with lock:
            await respond(bot, event)
            reward_data = None
            async with create_session() as session:
                qq_nickname = event.sender.nickname or event.sender.card or ""
                user, sign, _ = await register_user(session, uid, qq_nickname)
                is_new_sign = can_sign_today(sign)

                if is_new_sign:
                    reward_data = await execute_sign_update(user, sign, session)
                    await session.refresh(user)
                    await session.refresh(sign)

            image_message = await render_sign_card(
                user_name=username,
                user=user,
                sign=sign,
                reward_data=reward_data,
            )
    except Exception:
        logger.exception("签到处理失败")
    finally:
        sign_locks.pop(uid, None)

    if image_message is None:
        await sign_matcher.finish("抱歉，円香现在心情不太好，无法签到。")
    await sign_matcher.finish(image_message)
