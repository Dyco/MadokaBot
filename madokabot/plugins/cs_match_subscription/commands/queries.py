"""CS 帮助、赛事列表和比赛查询。"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot_plugin_alconna import Arparma, Match

from madokabot.core.messaging.response import respond

from ..assets import enrich_event_assets
from ..client import HltvError, fetch_match, filter_events, match_id_from_url
from ..event_catalog import get_local_events
from ..matchers import CS_USAGE, UNSUPPORTED_LINK_MESSAGE, cs_cmd
from ..render import render_event_list_card
from ..storage import save_checked_match, target_from_event
from ..subscriptions.delivery import send_rating_forward
from ..subscriptions.rating import render_check_rating_messages


@cs_cmd.handle()
async def handle_cs_root(result: Arparma) -> None:
    """未指定子命令时返回 CS 用法。"""
    if not result.subcommands:
        await cs_cmd.finish(CS_USAGE)


@cs_cmd.assign("subcommands.help")
async def handle_cs_help() -> None:
    """返回 CS 命令帮助。"""
    await cs_cmd.finish(CS_USAGE)


async def show_cs_events() -> None:
    """从本地赛事库筛选进行中及未来三个月赛事，再生成列表卡片。"""
    try:
        events = filter_events(await get_local_events())
        enrich_event_assets(events)
        image = await render_event_list_card(events)
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV赛事列表查询失败，请之后重试：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事列表查询失败")
        await cs_cmd.finish("HLTV赛事列表处理失败，请稍后重试。")
        return
    await cs_cmd.finish(Message([image]))


@cs_cmd.assign("subcommands.check")
async def handle_cs_check(
    bot: Bot,
    event: MessageEvent,
    match_url: Match[str],
) -> None:
    """解析并存档比赛数据，再发送单图或合并转发 Rating。"""
    await respond(bot, event)
    raw_url = match_url.result.strip() if match_url.available else ""
    match_id = match_id_from_url(raw_url) if len(raw_url.split()) == 1 else None
    if match_id is None:
        await cs_cmd.finish(UNSUPPORTED_LINK_MESSAGE)
        return

    try:
        match = await fetch_match(match_id, page_url=raw_url)
        try:
            await save_checked_match(match)
        except Exception:
            logger.exception("CS 比赛查询存档失败：match_id=%s", match_id)
        messages = await render_check_rating_messages(match)
    except HltvError as exc:
        logger.warning("CS 比赛链接解析失败：%s (%s)", raw_url, exc)
        await cs_cmd.finish(f"HLTV比赛信息查询失败，请之后重试：{exc}")
        return
    except Exception:
        logger.exception("CS 比赛 Rating 查询失败：%s", raw_url)
        await cs_cmd.finish("HLTV比赛信息查询失败或图片渲染失败，请稍后重试。")
        return

    if not messages:
        await cs_cmd.finish("没有解析到可用的比赛 Rating 数据。")
        return
    if len(messages) == 1:
        await cs_cmd.finish(messages[0])
        return

    target = target_from_event(event)
    if target is None or not await send_rating_forward(bot, target, messages):
        await cs_cmd.finish("合并消息发送失败，请稍后重试。")
        return
    await cs_cmd.finish()
