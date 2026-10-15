"""CS 竞猜参与、下注详情和排行榜命令。"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent, MessageSegment
from nonebot_plugin_alconna import Match

from madokabot.core.config import command_start
from madokabot.core.messaging.response import respond

from ..matchers import CS_PREDICTION_USAGE, cs_cmd
from ..prediction import (
    PredictionError,
    get_current_prediction_details,
    get_prediction_personal_records,
    get_prediction_ranking,
    place_prediction,
)
from ..render import render_prediction_personal_card, render_prediction_rank_card
from ..storage import get_hltv_event_settings
from ..subscriptions.delivery import send_forward_to_target


async def _show_prediction_details(bot: Bot, event: GroupMessageEvent) -> None:
    """按每场状态总览及双方名单三个节点合并转发跨群下注详情。"""
    try:
        details = await get_current_prediction_details(str(event.group_id))
    except Exception:
        logger.exception("CS 当前竞猜详情查询失败：group_id=%s", event.group_id)
        await cs_cmd.finish("竞猜详情查询失败，请稍后重试。")
        return
    if not details:
        await cs_cmd.finish("当前无竞猜比赛")
        return

    messages = []
    for detail in details:
        first, second = detail["teams"]
        lines = [
            f"【{first['name']} VS {second['name']}】下注情况",
            detail["status"],
        ]
        for team in detail["teams"]:
            lines.extend((
                f"{team['name']} - {team['odds']:.1f}",
                f"共计{team['count']}人，合计{team['points']}积分",
            ))
        messages.append(Message(MessageSegment.text("\n".join(lines))))
        for team in detail["teams"]:
            lines = [f"——{team['name']}——"]
            lines.extend(
                f"{player['name']} - {player['points']}积分" for player in team["players"]
            )
            if not team["players"]:
                lines.append("没有用户下注")
            messages.append(Message(MessageSegment.text("\n".join(lines))))
    try:
        sent = await send_forward_to_target(
            bot, {"kind": "group", "id": str(event.group_id)}, messages,
        )
    except Exception:
        logger.exception("CS 当前竞猜详情发送失败：group_id=%s", event.group_id)
        sent = False
    if not sent:
        await cs_cmd.finish("合并消息发送失败，请稍后重试。")
        return
    await cs_cmd.finish()


async def _finish_prediction_failure(bot: Bot, event: MessageEvent, reason: str) -> None:
    """竞猜失败回复方法。"""
    await respond(bot, event, emoji_id=479)
    await cs_cmd.finish(reason)


@cs_cmd.assign("subcommands.prediction")
async def handle_cs_prediction(
    bot: Bot,
    event: MessageEvent,
    params: Match[str],
) -> None:
    """处理竞猜参与、下注详情和排行榜查询。"""
    raw_params = params.result.strip() if params.available else ""
    prediction_args = raw_params.split()
    is_ranking = bool(prediction_args and prediction_args[0].casefold() in {"rank", "排名", "排行"})
    is_details = bool(
        prediction_args and prediction_args[0].casefold() in {"details", "详情", "细节", "内容", "详细"}
    )
    if not isinstance(event, GroupMessageEvent):
        if is_ranking or is_details:
            await cs_cmd.finish("竞猜功能仅支持群聊。")
        else:
            await _finish_prediction_failure(bot, event, "竞猜功能仅支持群聊。")
        return

    if is_details:
        if len(prediction_args) != 1:
            await cs_cmd.finish(f"用法：{command_start}CS prediction details")
            return
        await _show_prediction_details(bot, event)
        return

    if is_ranking:
        if len(prediction_args) != 2:
            await cs_cmd.finish(f"用法：{command_start}CS prediction rank <本群|全部|个人>")
            return
        scope_value = prediction_args[1].casefold()
        if scope_value in {"个人", "本人"}:
            try:
                data = await get_prediction_personal_records(str(event.user_id))
                image = await render_prediction_personal_card(data)
            except Exception:
                logger.exception("CS 竞猜个人记录处理失败：user_id=%s", event.user_id)
                await cs_cmd.finish("竞猜个人记录处理失败，请稍后重试。")
                return
            await cs_cmd.finish(Message([image]))
            return
        if scope_value in {"本群", "group"}:
            scope = "group"
            scope_label = "本群"
        elif scope_value in {"全部", "all"}:
            scope = "all"
            scope_label = "全部赛事"
        else:
            await cs_cmd.finish(f"用法：{command_start}CS prediction rank <本群|全部|个人>")
            return
        try:
            entries = await get_prediction_ranking(scope, str(event.group_id))
            image = await render_prediction_rank_card(
                entries,
                scope_label=scope_label,
            )
        except Exception:
            logger.exception("CS 竞猜排行榜渲染失败：scope=%s", scope)
            await cs_cmd.finish("竞猜排行榜处理失败，请稍后重试。")
            return
        await cs_cmd.finish(Message([image]))
        return

    if len(prediction_args) < 2:
        await _finish_prediction_failure(bot, event, CS_PREDICTION_USAGE)
        return
    if prediction_args[-1].isdigit():
        points_text = prediction_args[-1]
        team_name = " ".join(prediction_args[:-1])
    elif prediction_args[0].isdigit():
        points_text = prediction_args[0]
        team_name = " ".join(prediction_args[1:])
    else:
        await _finish_prediction_failure(bot, event, CS_PREDICTION_USAGE)
        return

    settings = get_hltv_event_settings(str(event.group_id))
    if not settings["prediction_enabled"]:
        await _finish_prediction_failure(
            bot, event, "本群尚未打开赛事竞猜功能，请先使用 CS event predict。",
        )
        return
    try:
        await place_prediction(
            str(event.group_id),
            str(event.user_id),
            team_name,
            int(points_text),
        )
    except PredictionError as exc:
        await _finish_prediction_failure(bot, event, str(exc))
        return
    except Exception:
        logger.exception(
            "CS 竞猜记录失败：group_id=%s user_id=%s",
            event.group_id,
            event.user_id,
        )
        await _finish_prediction_failure(bot, event, "竞猜记录失败，请稍后重试。")
        return
    await respond(bot, event, emoji_id=478)
    await cs_cmd.finish()
