"""CS 群赛事推送模式、通知与竞猜设置。"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot_plugin_alconna import Match

from ..commands.permissions import group_subscription_target
from ..matchers import CS_EVENT_USAGE, cs_cmd
from ..storage import (
    set_hltv_event_push_each_map,
    toggle_hltv_event_prediction,
    toggle_hltv_event_start_notification,
)


@cs_cmd.assign("subcommands.event")
async def handle_cs_event(
    bot: Bot,
    event: MessageEvent,
    params: Match[str],
) -> None:
    """解析赛事推送设置，避免使用嵌套子命令影响主命令解析。"""
    raw_params = params.result.strip() if params.available else ""
    event_args = raw_params.split()
    if len(event_args) != 1:
        await cs_cmd.finish(CS_EVENT_USAGE)

    option = event_args[0].casefold()
    if option in {"all", "全部"}:
        await _set_cs_event_mode(bot, event, push_each_map=False)
        return
    if option in {"single", "单图"}:
        await _set_cs_event_mode(bot, event, push_each_map=True)
        return
    if option in {"notif", "notification", "通知", "推送", "提醒"}:
        await _toggle_cs_event_notification(bot, event)
        return
    if option == "predict":
        await _toggle_cs_event_prediction(bot, event)
        return
    await cs_cmd.finish(CS_EVENT_USAGE)


async def _set_cs_event_mode(
    bot: Bot,
    event: MessageEvent,
    *,
    push_each_map: bool,
) -> None:
    """设置当前群的赛事推送粒度。"""
    target = await group_subscription_target(bot, event)
    if target is None:
        return
    set_hltv_event_push_each_map(target["id"], push_each_map)
    mode_text = "单图" if push_each_map else "全图"
    await cs_cmd.finish(f"已设置本群赛事推送方式为{mode_text}模式。")


async def _toggle_cs_event_notification(
    bot: Bot,
    event: MessageEvent,
) -> None:
    """切换当前群是否接收赛事开始通知。"""
    target = await group_subscription_target(bot, event)
    if target is None:
        return
    enabled = toggle_hltv_event_start_notification(target["id"])
    state_text = "已打开" if enabled else "已关闭"
    await cs_cmd.finish(f"{state_text}本群赛事开始通知")


async def _toggle_cs_event_prediction(
    bot: Bot,
    event: MessageEvent,
) -> None:
    """切换当前群是否开放赛事竞猜。"""
    target = await group_subscription_target(bot, event)
    if target is None:
        return
    enabled = toggle_hltv_event_prediction(target["id"])
    state_text = "已打开" if enabled else "已关闭"
    await cs_cmd.finish(f"{state_text}本群赛事竞猜功能")
