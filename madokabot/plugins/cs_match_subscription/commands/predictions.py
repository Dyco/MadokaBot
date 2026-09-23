"""CS 竞猜参与和排行榜命令。"""

from __future__ import annotations

from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot_plugin_alconna import Match

from ..matchers import CS_PREDICTION_USAGE, cs_cmd
from ..prediction import PredictionError, get_prediction_ranking, place_prediction
from ..render import render_prediction_rank_card
from ..storage import get_hltv_event_settings


@cs_cmd.assign("subcommands.prediction")
async def handle_cs_prediction(
    event: MessageEvent,
    params: Match[str],
) -> None:
    """解析竞猜和排行榜参数。"""
    if not isinstance(event, GroupMessageEvent):
        await cs_cmd.finish("竞猜功能仅支持群聊。")
        return

    raw_params = params.result.strip() if params.available else ""
    prediction_args = raw_params.split()
    if prediction_args and prediction_args[0].casefold() in {
        "rank",
        "排名",
    }:
        if len(prediction_args) != 2:
            await cs_cmd.finish("用法：CS prediction rank <本群|全部>")
            return
        scope_value = prediction_args[1].casefold()
        if scope_value in {"本群", "group"}:
            scope = "group"
            scope_label = "本群"
        elif scope_value in {"全部", "all"}:
            scope = "all"
            scope_label = "全部赛事"
        else:
            await cs_cmd.finish("用法：CS prediction rank <本群|全部>")
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
        await cs_cmd.finish(CS_PREDICTION_USAGE)
        return
    if prediction_args[0].isdigit():
        points_text = prediction_args[0]
        team_name = " ".join(prediction_args[1:])
    elif prediction_args[-1].isdigit():
        points_text = prediction_args[-1]
        team_name = " ".join(prediction_args[:-1])
    else:
        await cs_cmd.finish(CS_PREDICTION_USAGE)
        return

    settings = get_hltv_event_settings(str(event.group_id))
    if not settings["prediction_enabled"]:
        await cs_cmd.finish("本群尚未打开赛事竞猜功能，请先使用 CS event predict。")
        return
    try:
        result = await place_prediction(
            str(event.group_id),
            str(event.user_id),
            team_name,
            int(points_text),
        )
    except PredictionError as exc:
        await cs_cmd.finish(str(exc))
        return
    except Exception:
        logger.exception(
            "CS 竞猜记录失败：group_id=%s user_id=%s",
            event.group_id,
            event.user_id,
        )
        await cs_cmd.finish("竞猜记录失败，请稍后重试。")
        return
    await cs_cmd.finish(
        f"已使用{result['points']}积分预测{result['team_name']}获胜。"
        f"（比赛编号：{result['match_id']}）"
    )
