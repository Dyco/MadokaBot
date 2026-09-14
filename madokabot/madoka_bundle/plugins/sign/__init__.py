import asyncio
from collections import defaultdict

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import fullmatch
from nonebot_plugin_datastore import create_session

from ...render.utils import render_sign_card
from ..common.registration import register_user
from .config import SignConfig, config
from .utils import can_sign_today, execute_sign_update

__plugin_meta__ = PluginMetadata(
    name="每日签到",
    description="每日签到插件",
    usage="每日签到，用于获取积分",
    type="application",
    config=SignConfig,
)

sign_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

sign_keywords: list[str] = ["打卡", "签到","sign"] # 打卡关键词

sign_matcher = on_message(
    rule=fullmatch(config.sign_keywords),
    priority=10,
    block=True,
)


@sign_matcher.handle()
async def _handle_sign(event: MessageEvent):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname or uid
    lock = sign_locks[uid]
    if lock.locked():
        return

    image_message = None
    try:
        async with lock:
            reward_data = None
            async with create_session() as session:
                user, sign, _ = await register_user(session, uid)
                is_new_sign = can_sign_today(sign)

                if is_new_sign:
                    prompt = "签到成功！正在获得数据…"
                else:
                    prompt = "你已经签到过了。正在生成个人数据…"
                await sign_matcher.send(prompt)

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
