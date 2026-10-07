"""CS 竞猜参与和排行榜命令。"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot_plugin_alconna import Match

from madokabot.core.messaging.response import respond

from ..matchers import CS_PREDICTION_USAGE, cs_cmd
from ..prediction import (
    PredictionError,
    get_prediction_personal_records,
    get_prediction_ranking,
    place_prediction,
)
from ..render import render_prediction_personal_card, render_prediction_rank_card
from ..storage import get_hltv_event_settings


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
    """竞猜命令处理方法。"""
    raw_params = params.result.strip() if params.available else ""
    prediction_args = raw_params.split()
    is_ranking = bool(prediction_args and prediction_args[0].casefold() in {"rank", "排名"})
    if not isinstance(event, GroupMessageEvent):
        if is_ranking:
            await cs_cmd.finish("竞猜功能仅支持群聊。")
        else:
            await _finish_prediction_failure(bot, event, "竞猜功能仅支持群聊。")
        return

    if is_ranking:
        if len(prediction_args) != 2:
            await cs_cmd.finish("用法：CS prediction rank <本群|全部|个人|本人>")
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
            await cs_cmd.finish("用法：CS prediction rank <本群|全部|个人|本人>")
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
