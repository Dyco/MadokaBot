"""每日投胎会话处理。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot_plugin_alconna import Arparma

from madokabot.core.config import command_start
from madokabot.core.messaging.response import respond

from .matchers import reborn, reborn_cn, reborn_jp, reborn_us
from .modes import MODE_COMMANDS, RebornMode
from .render import render_reborn_card, result_text
from .service import REROLL_COST, reborn_today, reroll_today


@reborn.handle()
async def handle_reborn(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理世界投胎入口。"""
    await send_reborn(bot, event, command, mode="world")

@reborn_cn.handle()
async def handle_reborn_cn(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理中国投胎入口。"""
    await send_reborn(bot, event, command, mode="china")

@reborn_jp.handle()
async def handle_reborn_jp(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理日本投胎入口。"""
    await send_reborn(bot, event, command, mode="japan")

@reborn_us.handle()
async def handle_reborn_us(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理美国投胎入口。"""
    await send_reborn(bot, event, command, mode="usa")


async def send_reborn(bot: Bot, event: MessageEvent, command: Arparma, *, mode: RebornMode) -> None:
    """处理所选模式的免费投胎与重开，渲染失败时提供已保存结果的文字版。"""
    matcher = {"world": reborn, "china": reborn_cn, "japan": reborn_jp, "usa": reborn_us}[mode]
    command_name = MODE_COMMANDS[mode]
    await respond(bot, event)
    try:
        if "reroll" in command.subcommands:
            result, remaining = await reroll_today(event.get_user_id(), mode=mode)
            prefix = f"重开成功，消耗{REROLL_COST}积分，剩余{remaining}积分"
        else:
            result, created = await reborn_today(event.get_user_id(), mode=mode)
            prefix = "新的人生已开启" if created else (
                f"今天已经投胎过啦，这是结果。\n"
                f"可使用“{command_start}{command_name} 重开”消耗{REROLL_COST}积分重新投胎。"
            )
    except ValueError as exc:
        await matcher.finish(str(exc), reply_message=True)
    except Exception:
        logger.exception("每日投胎结果生成或保存失败")
        await matcher.finish("投胎结果暂时无法读取，请稍后重试。", reply_message=True)

    name = event.sender.card or event.sender.nickname or event.get_user_id()
    try:
        picture = await render_reborn_card(result, name)
    except Exception:
        logger.exception("每日投胎图片生成失败")
        await matcher.finish(result_text(result, prefix=prefix, name=name), reply_message=True)
    await matcher.finish(MessageSegment.text(prefix + "\n") + picture, reply_message=True)
