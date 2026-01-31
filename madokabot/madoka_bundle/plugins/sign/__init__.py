import asyncio

from nonebot import on_message, logger
from nonebot.rule import fullmatch
from nonebot.exception import FinishedException
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.plugin import PluginMetadata
from collections import defaultdict
from nonebot_plugin_datastore import create_session

from .config import SignConfig, config
from .utils import get_sign_status, execute_sign_update
from ...render.utils import render_sign_card


__plugin_meta__ = PluginMetadata(
    name="每日签到",
    description="每日签到插件",
    usage="每日签到，用于获取积分",
    type="application",
    config=SignConfig,
)

sign_locks = defaultdict(asyncio.Lock)
sign_generating = defaultdict(bool)

sign_matcher = on_message( rule=fullmatch(config.sign_keywords) , priority=10 , block=True )

@sign_matcher.handle()
async def _(event: MessageEvent):
    uid = event.get_user_id()
    username = event.sender.card or event.sender.nickname
    
    if sign_generating[uid]:
        return  

    async with sign_locks[uid]:
        sign_generating[uid] = True
        try:
            reward_data = None
            async with create_session() as session:
                user, sign, is_new = await get_sign_status(uid, session)
                
                prefix = "签到成功！正在获得数据…" if is_new else "你已经签到过了。正在生成个人数据…"
                await sign_matcher.send(prefix)

                if is_new:
                    reward_data = await execute_sign_update(user, sign, session)
                    await session.refresh(user)
                    await session.refresh(sign)
            
            # 传入参数：username, user, sign, reward_data
            image_msg = await render_sign_card(
                user_name=username, 
                user=user, 
                sign=sign, 
                reward_data=reward_data
            )
            
            await sign_matcher.finish(image_msg)

        except FinishedException:
            raise
        except Exception as e:
            import traceback
            logger.error(f"签到异常: {e}\n{traceback.format_exc()}")
            await sign_matcher.send("抱歉，円香现在心情不太好，稍后再来吧。")
        finally:
            sign_generating[uid] = False