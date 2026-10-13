"""CS 赛事订阅、退订和全局移除命令。"""

from __future__ import annotations

from datetime import datetime, timezone

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Match

from madokabot.core.config import command_start
from madokabot.core.messaging.response import respond

from ..client import HltvError, fetch_event, fetch_event_match_refs
from ..commands.permissions import group_subscription_target
from ..matchers import CS_REMOVESUB_USAGE, CS_UNSUB_USAGE, cs_cmd
from ..models import (
    EVENT_STATUS_FINISHED,
    MATCH_SECTION_UPCOMING,
    EventData,
    EventMatchRef,
)
from ..storage import (
    add_event_target_if_exists,
    get_hltv_event_settings,
    remove_event_subscription,
    subscribe_event,
    target_from_event,
    unsubscribe_all_events,
    unsubscribe_event,
)


def _event_schedule_text(event: EventData) -> str:
    """生成订阅成功消息中的赛事日期。"""
    if event.start_at is None:
        return "待定"

    def format_date(value: datetime) -> str:
        """将赛事日期转换为中文年月日。"""
        return f"{value.year}年{value.month}月{value.day}日"

    start_text = format_date(event.start_at)
    if event.end_at is None or event.end_at.date() == event.start_at.date():
        return start_text
    return f"{start_text} - {format_date(event.end_at)}"


def _event_is_finished(event: EventData, refs: list[EventMatchRef]) -> bool:
    """赛事结束检查方法。"""
    if event.is_finished:
        return True
    if event.event_status != "unknown":
        return False

    if not refs or any(ref.section == MATCH_SECTION_UPCOMING for ref in refs):
        return False
    if event.end_at is None:
        return False
    end_at = event.end_at
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    return end_at <= datetime.now(timezone.utc)


def _subscription_hint(target: dict[str, str], event_id: str) -> str:
    """生成群订阅回复中的竞猜状态、推送模式和退订提示。"""
    if target["kind"] != "group":
        return ""
    settings = get_hltv_event_settings(target["id"])
    prediction_state = "已打开" if settings["prediction_enabled"] else "已关闭"
    push_mode = "每图" if settings["push_each_map"] else "整场"
    return (
        f"本群竞猜{prediction_state}，采用{push_mode}推送，"
        f"使用{command_start}CS unsub {event_id} 可退订本群赛事推送。"
    )


@cs_cmd.assign("subcommands.sub")
async def handle_cs_sub(
    bot: Bot,
    event: MessageEvent,
    event_id: Match[str],
) -> None:
    """赛事订阅命令处理方法。"""
    raw_id = event_id.result.strip() if event_id.available else ""
    if not raw_id.isdigit():
        await cs_cmd.finish("赛事 ID 无效，请使用数字，例如：CS sub 8057")

    target = target_from_event(event)
    if target is None:
        await cs_cmd.finish("无法识别当前会话，暂时不能建立赛事订阅。")

    try:
        local_subscription = await add_event_target_if_exists(raw_id, target)
    except Exception:
        logger.exception("读取本地 CS 赛事订阅失败：%s", raw_id)
        local_subscription = None

    if local_subscription is not None:
        added, stored_entry = local_subscription
        stored_name = str(stored_entry.get("event_name") or "").strip()
        if not stored_name:
            event_data = stored_entry.get("event_data")
            if isinstance(event_data, dict):
                stored_name = str(event_data.get("name") or "").strip()
        stored_name = stored_name or raw_id

        if (
            stored_entry.get("completed", False)
            or str(stored_entry.get("status", "")) == EVENT_STATUS_FINISHED
        ):
            await cs_cmd.finish(f"赛事{stored_name}已结束，无法再订阅")
            return

        if added:
            await cs_cmd.finish(
                f"已成功订阅赛事【{stored_name}】。{_subscription_hint(target, raw_id)}"
            )
            return
        await cs_cmd.finish(
            f"当前会话已订阅赛事【{stored_name}】，已在推送列表中。"
            f"{_subscription_hint(target, raw_id)}"
        )
        return

    await respond(bot, event)
    try:
        event_data = await fetch_event(raw_id)
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV 查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事订阅失败：%s", raw_id)
        await cs_cmd.finish("HLTV 赛事订阅处理失败，请稍后重试。")
        return

    if event_data.is_finished:
        await cs_cmd.finish(f"赛事{event_data.name}已结束，无法再订阅")
        return

    try:
        refs = await fetch_event_match_refs(raw_id)
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV 查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事订阅失败：%s", raw_id)
        await cs_cmd.finish("HLTV 赛事订阅处理失败，请稍后重试。")
        return

    if _event_is_finished(event_data, refs):
        await cs_cmd.finish(f"赛事{event_data.name}已结束，无法再订阅")
        return

    try:
        added = await subscribe_event(
            raw_id,
            target,
            event_data=event_data,
            event_name=event_data.name,
            event_url=event_data.url,
            event_end=event_data.end_at.isoformat() if event_data.end_at else "",
            match_refs=[
                {
                    "match_id": ref.match_id,
                    "url": ref.url,
                    "section": ref.section,
                    "scheduled_at": (
                        ref.scheduled_at.isoformat() if ref.scheduled_at else ""
                    ),
                }
                for ref in refs
            ],
        )
    except Exception:
        logger.exception("CS 赛事订阅失败：%s", raw_id)
        await cs_cmd.finish("HLTV 赛事订阅处理失败，请稍后重试。")
        return

    prefix = "已成功订阅赛事" if added else "已刷新赛事订阅"
    await cs_cmd.finish(
        f"{prefix}【{event_data.name}】，时间为{_event_schedule_text(event_data)}。"
        f"{_subscription_hint(target, raw_id)}"
    )


@cs_cmd.assign("subcommands.unsub")
async def handle_cs_unsub(
    bot: Bot,
    event: MessageEvent,
    event_id: Match[str],
) -> None:
    """让当前群退订指定赛事。"""
    target = await group_subscription_target(bot, event)
    if target is None:
        return

    raw_id = event_id.result.strip() if event_id.available else ""
    if not raw_id.isdigit():
        await cs_cmd.finish(CS_UNSUB_USAGE)
        return

    try:
        removed, event_name = await unsubscribe_event(raw_id, target)
    except Exception:
        logger.exception("CS 指定赛事退订失败：event_id=%s", raw_id)
        await cs_cmd.finish("赛事退订处理失败，请稍后重试。")
        return

    if not removed:
        await cs_cmd.finish(f"本群未订阅赛事{event_name}。")
        return
    await cs_cmd.finish(
        f"本群已退订赛事{event_name}（{raw_id}），不再接收该赛事推送。"
        f"使用 CS sub {raw_id} 可重新订阅。"
    )


@cs_cmd.assign("subcommands.nosub")
async def handle_cs_nosub(bot: Bot, event: MessageEvent) -> None:
    """让当前群退订全部赛事推送。"""
    target = await group_subscription_target(bot, event)
    if target is None:
        return

    try:
        removed = await unsubscribe_all_events(target)
    except Exception:
        logger.exception("CS 全部赛事退订失败：group_id=%s", event.group_id)
        await cs_cmd.finish("赛事退订处理失败，请稍后重试。")
        return

    if not removed:
        await cs_cmd.finish("本群当前没有赛事订阅。")
        return
    await cs_cmd.finish(
        f"本群已退订全部赛事推送，共移除 {removed} 项订阅。"
        "使用 CS sub <赛事ID> 可重新订阅指定赛事。"
    )


@cs_cmd.assign("subcommands.removesub")
async def handle_cs_removesub(
    bot: Bot,
    event: MessageEvent,
    event_id: Match[str],
) -> None:
    """由超级用户全局移除指定赛事订阅。"""
    if not await SUPERUSER(bot, event):
        await cs_cmd.finish("权限不足，只有超级用户可以使用此命令。")
        return

    raw_id = event_id.result.strip() if event_id.available else ""
    if not raw_id.isdigit():
        await cs_cmd.finish(CS_REMOVESUB_USAGE)
        return

    try:
        removed, event_name = await remove_event_subscription(raw_id)
    except Exception:
        logger.exception("CS 全局赛事移除失败：event_id=%s", raw_id)
        await cs_cmd.finish("赛事移除处理失败，请稍后重试。")
        return

    if not removed:
        await cs_cmd.finish(f"未找到赛事订阅：{raw_id}")
        return
    await cs_cmd.finish(
        f"已全局移除赛事{event_name}（{raw_id}），所有推送目标均已删除。"
        f"使用 CS sub {raw_id} 可为当前会话重新订阅。"
    )
