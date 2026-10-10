"""每日投胎会话处理。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot_plugin_alconna import Arparma

from madokabot.core.messaging.response import respond
from .matchers import reborn
from .render import render_reborn_card, result_text
from .service import REROLL_COST, reborn_today, reroll_today


@reborn.handle()
async def handle_reborn(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理免费投胎与积分重开，图片渲染失败时提供相同结果的文字版。"""
    await respond(bot, event)
    try:
        if "reroll" in command.subcommands:
            result, remaining = await reroll_today(event.get_user_id())
            prefix = f"重开成功，消耗 {REROLL_COST} 积分，剩余 {remaining} 积分。"
        else:
            result, created = await reborn_today(event.get_user_id())
            prefix = "新的人生已开启。" if created else "今天已经投胎过啦，这是你今天的结果。\n可以消耗积分进行重开，指令为/投胎 重开。"
    except ValueError as exc:
        await reborn.finish(str(exc))
    except Exception:
        logger.exception("每日投胎结果生成或保存失败")
        await reborn.finish("投胎结果暂时无法读取，请稍后重试。")

    name = event.sender.card or event.sender.nickname or event.get_user_id()
    try:
        picture = await render_reborn_card(result, name)
    except Exception:
        logger.exception("每日投胎图片生成失败")
        await reborn.finish(result_text(result, prefix=prefix))
    await reborn.finish(MessageSegment.text(prefix + "\n") + picture)
