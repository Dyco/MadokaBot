"""每日投胎会话处理。"""

from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot_plugin_alconna import Arparma

from madokabot.core.config import command_start
from madokabot.core.messaging.response import respond

from .matchers import (
    reborn,
    reborn_all,
    reborn_anime,
    reborn_cn,
    reborn_games,
    reborn_isekai,
    reborn_jp,
    reborn_us,
)
from .modes import MODE_COMMANDS, RebornMode
from .render import render_reborn_card, result_text
from .service import REROLL_COST, reborn_all_today, reborn_today, reroll_today
from .text import combined_result_text


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


@reborn_isekai.handle()
async def handle_reborn_isekai(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理四类世界共用每日机会的异世界投胎入口。"""
    await send_reborn(bot, event, command, mode="isekai")


@reborn_anime.handle()
async def handle_reborn_anime(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理所有作品共用每日机会的二次元投胎入口。"""
    await send_reborn(bot, event, command, mode="anime")


@reborn_games.handle()
async def handle_reborn_games(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """处理二游身份抽取、每日查看与积分重开。"""
    await send_reborn(bot, event, command, mode="games")


@reborn_all.handle()
async def handle_reborn_all(bot: Bot, event: MessageEvent, command: Arparma) -> None:
    """将全部模式的当天投胎或重开结果按顺序作为纯文字合并发送。"""
    await respond(bot, event)
    try:
        results, remaining = await reborn_all_today(event.get_user_id(), reroll="reroll" in command.subcommands)
    except ValueError as exc:
        await reborn_all.finish(str(exc))
    except Exception:
        logger.exception("一键投胎结果生成或保存失败")
        await reborn_all.finish("投胎结果暂时无法读取，请稍后重试。")

    name = event.sender.card or event.sender.nickname or event.get_user_id()
    messages = [f"{name} 的今日投胎", *(combined_result_text(result) for result in results)]
    nodes = [
        MessageSegment.node_custom(
            user_id=bot.self_id, nickname="每日投胎", content=Message(MessageSegment.text(text)),
        )
        for text in messages
    ]
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.send_group_forward_msg(group_id=event.group_id, messages=nodes)
        else:
            await bot.send_private_forward_msg(user_id=event.user_id, messages=nodes)
    except Exception:
        logger.exception("一键投胎合并消息发送失败")
        await reborn_all.finish("合并消息发送失败，可使用一键投胎查看已保存的结果。")
    if remaining is not None:
        await reborn_all.finish(f"全部重开成功，消耗{REROLL_COST * len(results)}积分，剩余{remaining}积分")
    await reborn_all.finish()


async def send_reborn(bot: Bot, event: MessageEvent, command: Arparma, *, mode: RebornMode) -> None:
    """处理所选模式的免费投胎与重开，渲染失败时提供已保存结果的文字版。"""
    matcher = {
        "world": reborn, "china": reborn_cn, "japan": reborn_jp,
        "usa": reborn_us, "isekai": reborn_isekai, "anime": reborn_anime, "games": reborn_games,
    }[mode]
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
