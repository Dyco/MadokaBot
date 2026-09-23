"""CS 帮助、赛事列表、竞猜详情和比赛查询。"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot_plugin_alconna import Arparma, Match

from madokabot.core.messaging.response import respond

from ..assets import enrich_event_assets
from ..client import HltvError, fetch_events, fetch_match, match_id_from_url
from ..matchers import CS_USAGE, UNSUPPORTED_LINK_MESSAGE, cs_cmd
from ..prediction import get_prediction_detail
from ..render import render_event_list_card
from ..storage import target_from_event
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


@cs_cmd.assign("subcommands.list")
async def handle_cs_list(
    event: MessageEvent,
    params: Match[str],
) -> None:
    """解析 list 的二级参数并执行对应查询。"""
    raw_params = params.result.strip() if params.available else ""
    list_args = raw_params.split()
    if len(list_args) == 1 and list_args[0].isdigit():
        if not isinstance(event, GroupMessageEvent):
            await cs_cmd.finish("竞猜功能仅支持群聊。")
            return
        try:
            detail = await get_prediction_detail(
                str(event.group_id),
                list_args[0],
            )
        except Exception:
            logger.exception(
                "CS 竞猜详情查询失败：group_id=%s match_id=%s",
                event.group_id,
                list_args[0],
            )
            await cs_cmd.finish("竞猜详情查询失败，请稍后重试。")
            return
        if detail is None:
            await cs_cmd.finish("未找到本群可查看的竞猜比赛。")
            return
        team_names = detail["team_names"]
        first = team_names[0] if len(team_names) > 0 else "队伍A"
        second = team_names[1] if len(team_names) > 1 else "队伍B"
        teams = detail["summary"]["teams"]
        first_summary = teams.get(first, {})
        second_summary = teams.get(second, {})
        lines = [
            f"【比赛编号：{detail['match_id']}】",
            f"{first}对阵{second}，{detail['status']}。",
            f"{first}：{first_summary.get('count', 0)}人预测，共计"
            f"{first_summary.get('points', 0)}积分。",
            f"{second}：{second_summary.get('count', 0)}人预测，共计"
            f"{second_summary.get('points', 0)}积分。",
        ]
        if detail["winner_name"]:
            lines.append(
                f"获胜队伍：{detail['winner_name']}（每人获得"
                f"{detail['payout_per_winner']}积分）"
            )
        await cs_cmd.finish("\n".join(lines))
        return

    if len(list_args) != 1 or list_args[0].casefold() != "event":
        await cs_cmd.finish("用法：CS list event | <比赛ID>")
        return

    try:
        events = await fetch_events()
        await enrich_event_assets(events)
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
    """解析比赛链接并发送单图或合并转发 Rating。"""
    await respond(bot, event)
    raw_url = match_url.result.strip() if match_url.available else ""
    match_id = match_id_from_url(raw_url) if len(raw_url.split()) == 1 else None
    if match_id is None:
        await cs_cmd.finish(UNSUPPORTED_LINK_MESSAGE)
        return

    try:
        match = await fetch_match(match_id, page_url=raw_url)
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
