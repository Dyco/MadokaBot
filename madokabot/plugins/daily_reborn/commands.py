"""每日投胎会话处理。"""

from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot_plugin_alconna import Arparma

from madokabot.core.messaging.response import respond
from .matchers import reborn, reborn_cn
from .render import render_reborn_card, result_text
from .service import REROLL_COST, reborn_today, reroll_today


@reborn.handle()
async def handle_reborn(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理世界投胎入口。"""
    await send_reborn(bot, event, command, china=False)


@reborn_cn.handle()
async def handle_reborn_cn(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理中国投胎入口。"""
    await send_reborn(bot, event, command, china=True)


async def send_reborn(bot: Bot, event: MessageEvent, command: Arparma, *, china: bool) -> None:
    """处理所选模式的免费投胎与重开，渲染失败时提供已保存结果的文字版。"""
    matcher = reborn_cn if china else reborn
    command_name = "投胎中国" if china else "投胎"
    starts = get_driver().config.command_start
    command_start = "/" if "/" in starts else min(starts, default="")
    await respond(bot, event)
    try:
        if "reroll" in command.subcommands:
            result, remaining = await reroll_today(event.get_user_id(), china=china)
            prefix = f"重开成功，消耗 {REROLL_COST} 积分，剩余 {remaining} 积分。"
        else:
            result, created = await reborn_today(event.get_user_id(), china=china)
            prefix = "新的人生已开启。" if created else (
                f"今天已经投胎过啦，这是你今天的结果。\n"
                f"可使用“{command_start}{command_name} 重开”消耗 {REROLL_COST} 积分重新投胎。"
            )
    except ValueError as exc:
        await matcher.finish(str(exc))
    except Exception:
        logger.exception("每日投胎结果生成或保存失败")
        await matcher.finish("投胎结果暂时无法读取，请稍后重试。")

    name = event.sender.card or event.sender.nickname or event.get_user_id()
    try:
        picture = await render_reborn_card(result, name)
    except Exception:
        logger.exception("每日投胎图片生成失败")
        await matcher.finish(result_text(result, prefix=prefix))
    await matcher.finish(MessageSegment.text(prefix + "\n") + picture)
