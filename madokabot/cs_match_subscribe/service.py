"""赛事订阅轮询和合并转发服务。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .assets import enrich_match_assets
from .client import HltvError, fetch_event_match_refs, fetch_match
from .models import EventMatchRef, MapScore, MatchData
from .render import render_rating_card
from .storage import (
    list_active,
    list_active_events,
    update_event_state,
    update_state,
)

_MAP_LABELS = "一二三四五六七八九十"


def _team_names(match: MatchData) -> tuple[str, str]:
    """获取比赛双方名称。"""
    first = match.teams[0].name if match.teams else "队伍A"
    second = match.teams[1].name if len(match.teams) > 1 else "队伍B"
    return first, second


def _format_score(match: MatchData, *, series: bool = False) -> str:
    """生成系列赛或地图的中文比分。"""
    first, second = _team_names(match)
    scores = " : ".join(team.score or "-" for team in match.teams[:2])
    if series:
        scores = scores.replace(" : ", ":")
    return f"{first} {scores or '-'} {second}"


def _summary(match: MatchData) -> str:
    """生成旧版单场订阅仍使用的简短文本。"""
    event = f" | {match.event_name}" if match.event_name else ""
    return f"CS赛事更新：{match.display_title} {_format_score(match)}（{match.status_text or match.status}）{event}"


def _start_message(match: MatchData, event_name: str = "") -> Message:
    """生成比赛正式开始的合并转发文本节点。"""
    first, second = _team_names(match)
    event_prefix = f"【{event_name}】" if event_name else ""
    format_code = match.format_code or "未知"
    lines = [
        f"{event_prefix}订阅赛事正式开始",
        f"{first} 对阵 {second}，赛制为 {format_code}",
    ]
    if match.format_text:
        lines.extend(("", match.format_text))
    return Message(MessageSegment.text("\n".join(lines)))


def _map_result_message(match: MatchData, result: MapScore, index: int) -> Message:
    """生成单张地图结束的合并转发文本节点。"""
    first, second = _team_names(match)
    label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
    text = (
        f"订阅赛事更新\n{first} 对阵 {second} 的图{label}结束，"
        f"比分为 {first} {result.score_display} {second}"
    )
    return Message(MessageSegment.text(text))


def _final_message(match: MatchData) -> Message:
    """生成系列赛结束的合并转发文本节点。"""
    return Message(
        MessageSegment.text(
            f"订阅赛事更新\n{match.display_title} 比赛结束，系列赛比分为："
            f"{_format_score(match, series=True)}"
        )
    )


async def _send_to_target(
    bot: Bot,
    target: dict[str, str],
    message: Message,
) -> bool:
    """发送普通 OneBot 消息，兼容历史单场订阅。"""
    kind = target.get("kind")
    target_id = target.get("id")
    if not target_id:
        return False
    if kind == "group":
        await bot.call_api("send_group_msg", group_id=int(target_id), message=message)
        return True
    if kind == "private":
        await bot.call_api("send_private_msg", user_id=int(target_id), message=message)
        return True
    return False


async def _send_forward_to_target(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """通过 OneBot 的 forward API 发送自定义节点。"""
    kind = target.get("kind")
    target_id = target.get("id")
    if not target_id or not messages:
        return False

    sender_id = int(str(bot.self_id)) if str(bot.self_id).isdigit() else 0
    nodes = [
        MessageSegment.node_custom(sender_id, "HLTV赛事订阅", content)
        for content in messages
    ]
    try:
        if kind == "group":
            await bot.send_group_forward_msg(
                group_id=int(target_id),
                messages=nodes,
            )
            return True
        if kind == "private":
            await bot.send_private_forward_msg(
                user_id=int(target_id),
                messages=nodes,
            )
            return True
    except Exception as exc:
        logger.warning("HLTV 合并转发发送失败，降级为普通文本：%s", exc)
        fallback = "\n\n".join(
            message.extract_plain_text().strip()
            for message in messages
            if message.extract_plain_text().strip()
        )
        if fallback:
            return await _send_to_target(bot, target, Message(fallback))
    return False


async def send_rating_forward(
    bot: Bot,
    target: dict[str, str],
    messages: list[Message],
) -> bool:
    """发送比赛 Rating 图片合并转发。"""
    return await _send_forward_to_target(bot, target, messages)


def _available_bots() -> Iterable[Bot]:
    """获取当前可用于推送的 OneBot V11 连接。"""
    return [bot for bot in get_bots().values() if isinstance(bot, Bot)]


async def _broadcast(
    targets: list[dict[str, str]],
    message: Message,
    *,
    bot: Bot | None = None,
) -> bool:
    """广播普通消息，并返回是否全部目标发送成功。"""
    bots = [bot] if bot is not None else list(_available_bots())
    if not bots:
        logger.warning("没有可用 OneBot 连接，暂不推送 HLTV 赛事更新。")
        return False
    if not targets:
        logger.warning("HLTV 赛事订阅没有有效推送目标，暂不更新订阅状态。")
        return False
    delivered_all = True
    for target in targets:
        delivered = False
        for current_bot in bots:
            try:
                if await _send_to_target(current_bot, target, message):
                    delivered = True
                    break
            except Exception:
                logger.exception("推送 HLTV 赛事更新失败：%s", target)
        delivered_all = delivered_all and delivered
    return delivered_all


async def _broadcast_forward(
    targets: list[dict[str, str]],
    messages: list[Message],
) -> bool:
    """将一个赛事更新批次作为合并转发广播。"""
    bots = list(_available_bots())
    if not bots:
        logger.warning("没有可用 OneBot 连接，暂不推送 HLTV 赛事更新。")
        return False
    if not targets:
        logger.warning("HLTV 赛事订阅没有有效推送目标，暂不更新订阅状态。")
        return False

    delivered_all = True
    for target in targets:
        delivered = False
        for bot in bots:
            try:
                if await _send_forward_to_target(bot, target, messages):
                    delivered = True
                    break
            except Exception:
                logger.exception("推送 HLTV 合并转发失败：%s", target)
        delivered_all = delivered_all and delivered
    return delivered_all


def _current_map_scores(match: MatchData) -> dict[str, str]:
    """获取当前页面上已经产生最终比分的地图。"""
    scores: dict[str, str] = {}
    for index, result in enumerate(match.map_results):
        if result.is_finished:
            scores[f"{index}:{result.name}"] = result.score_display
    return scores


def _new_match_state(section: str) -> dict[str, Any]:
    """创建一场新发现比赛的轮询状态。"""
    return {
        "source": section,
        "initialized": False,
        "historical": False,
        "started_sent": False,
        "final_sent": False,
        "completed": False,
        "map_scores": {},
        "notified_maps": [],
    }


def _historical_match_state() -> dict[str, Any]:
    """创建订阅前已经结束比赛的基线状态。"""
    state = _new_match_state("result")
    state.update(
        {
            "initialized": True,
            "historical": True,
            "started_sent": True,
            "final_sent": True,
            "completed": True,
        }
    )
    return state


def _match_belongs_to_event(
    match: MatchData,
    event_id: str,
    event_name: str,
) -> bool:
    """过滤赛事列表页侧栏混入的其他比赛。"""
    if match.event_url and f"/events/{event_id}" not in match.event_url:
        return False
    if not match.event_url and event_name and match.event_name:
        return match.event_name == event_name
    return True


async def _rating_message(
    match: MatchData,
    cache: dict[str, MessageSegment],
    map_name: str | None = None,
) -> Message | None:
    """渲染指定统计范围的 Rating 图片节点。"""
    if not match.has_stats:
        return None
    if map_name and map_name not in match.map_stats:
        return None
    cache_key = map_name or "all"
    if cache_key not in cache:
        match = await enrich_match_assets(match)
        cache[cache_key] = await render_rating_card(match, map_name=map_name)
    return Message(cache[cache_key])


async def render_check_rating_messages(match: MatchData) -> list[Message]:
    """按比赛地图数量生成即时查询所需的 Rating 消息。"""
    if not match.has_stats:
        return []

    match = await enrich_match_assets(match)
    map_names = [name for name in match.maps if name in match.map_stats]
    if not map_names:
        map_names = list(match.map_stats)

    if len(map_names) <= 1:
        map_name = map_names[0] if map_names else None
        return [Message(await render_rating_card(match, map_name=map_name))]

    messages: list[Message] = []
    for index, map_name in enumerate(map_names):
        image = await render_rating_card(match, map_name=map_name)
        label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
        messages.append(
            Message(
                [
                    MessageSegment.text(f"图{label}（{map_name}）\n"),
                    image,
                ]
            )
        )

    total_image = await render_rating_card(match)
    messages.append(
        Message([MessageSegment.text("总数据\n"), total_image])
    )
    return messages


async def _process_event_match(
    match: MatchData,
    state: dict[str, Any],
    event_name: str,
) -> list[Message]:
    """根据一次比赛快照生成尚未推送的节点并更新内存状态。"""
    messages: list[Message] = []
    initialized = bool(state.get("initialized", False))
    previous_scores = state.get("map_scores")
    if not isinstance(previous_scores, dict):
        previous_scores = {}
    if not initialized and not match.has_started:
        previous_scores = _current_map_scores(match)

    if match.has_started and not state.get("started_sent", False):
        messages.append(_start_message(match, event_name))
        state["started_sent"] = True

    notified = state.get("notified_maps")
    if not isinstance(notified, list):
        notified = []
        state["notified_maps"] = notified
    notified_set = {str(value) for value in notified}
    rating_cache: dict[str, MessageSegment] = {}
    current_scores = _current_map_scores(match)
    for index, result in enumerate(match.map_results):
        if not result.is_finished:
            continue
        key = f"{index}:{result.name}"
        score = result.score_display
        if key in notified_set or previous_scores.get(key) == score:
            continue
        messages.append(_map_result_message(match, result, index))
        image = await _rating_message(match, rating_cache, result.name)
        if image is not None:
            messages.append(image)
        notified.append(key)
        notified_set.add(key)

    if match.is_finished and not state.get("final_sent", False):
        messages.append(_final_message(match))
        image = await _rating_message(match, rating_cache)
        if image is not None:
            messages.append(image)
        state["final_sent"] = True
        state["completed"] = True

    state["initialized"] = True
    state["map_scores"] = current_scores
    return messages


async def _load_event_matches(
    refs: list[EventMatchRef],
) -> list[tuple[EventMatchRef, MatchData]]:
    """并发抓取赛事中需要继续跟踪的比赛详情。"""
    semaphore = asyncio.Semaphore(4)

    async def load(ref: EventMatchRef) -> tuple[EventMatchRef, MatchData] | None:
        async with semaphore:
            try:
                return ref, await fetch_match(ref.match_id)
            except HltvError as exc:
                logger.warning("轮询 HLTV 比赛 %s 失败：%s", ref.match_id, exc)
            except Exception:
                logger.exception("处理 HLTV 比赛订阅失败：%s", ref.match_id)
        return None

    results = await asyncio.gather(*(load(ref) for ref in refs))
    return [result for result in results if result is not None]


def _event_ended(entry: dict[str, Any]) -> bool:
    """判断赛事是否已经结束且所有比赛均已处理。"""
    value = entry.get("event_end")
    if not isinstance(value, str) or not value:
        return False
    try:
        end_at = datetime.fromisoformat(value)
    except ValueError:
        return False
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    matches = entry.get("matches")
    return bool(matches) and end_at <= datetime.now(timezone.utc) and all(
        isinstance(state, dict) and state.get("completed", False)
        for state in matches.values()
    )


async def _poll_event_subscription(
    event_id: str,
    entry: dict[str, Any],
) -> None:
    """轮询一个赛事并合并发送本轮新增节点。"""
    refs = await fetch_event_match_refs(event_id)
    stored_matches = entry.get("matches")
    matches = stored_matches if isinstance(stored_matches, dict) else {}
    baseline_ids = {
        str(value)
        for value in entry.get("baseline_match_ids", [])
        if str(value).isdigit()
    }
    ref_by_id = {ref.match_id: ref for ref in refs}
    pending_refs: list[EventMatchRef] = []

    for ref in refs:
        state = matches.get(ref.match_id)
        if isinstance(state, dict):
            if not state.get("completed", False):
                pending_refs.append(ref)
            continue
        if ref.section == "result" and ref.match_id in baseline_ids:
            matches[ref.match_id] = _historical_match_state()
            continue
        matches[ref.match_id] = _new_match_state(ref.section)
        pending_refs.append(ref)

    # 页面列表可能暂时漏掉刚从 matches 移到 results 的比赛，继续跟踪已有状态。
    for match_id, state in matches.items():
        if (
            isinstance(state, dict)
            and not state.get("completed", False)
            and match_id not in ref_by_id
            and str(match_id).isdigit()
        ):
            pending_refs.append(
                EventMatchRef(
                    match_id=str(match_id),
                    url="",
                    section=str(state.get("source", "upcoming")),
                )
            )

    loaded = await _load_event_matches(pending_refs)
    messages: list[Message] = []
    event_name = str(entry.get("event_name", ""))
    for ref, match in loaded:
        if not _match_belongs_to_event(match, event_id, event_name):
            matches[ref.match_id] = _historical_match_state()
            continue
        state = matches[ref.match_id]
        messages.extend(await _process_event_match(match, state, event_name))

    targets = [
        target
        for target in entry.get("targets", [])
        if isinstance(target, dict)
    ]
    if messages:
        if not await _broadcast_forward(targets, messages):
            return

    await update_event_state(
        event_id,
        matches=matches,
        completed=_event_ended({**entry, "matches": matches}),
    )


async def _poll_legacy_matches() -> None:
    """兼容旧版按比赛 ID 保存的订阅。"""
    entries = await list_active()
    for match_id, entry in entries.items():
        try:
            match = await fetch_match(match_id)
            fingerprint = match.fingerprint()
            previous = entry.get("fingerprint")
            if previous == fingerprint:
                continue

            targets = [
                target
                for target in entry.get("targets", [])
                if isinstance(target, dict)
            ]
            if match.is_finished and match.has_stats:
                match = await enrich_match_assets(match)
                image = await render_rating_card(match)
                message = Message([MessageSegment.text(_summary(match) + "\n"), image])
                if await _broadcast(targets, message):
                    await update_state(match_id, fingerprint=fingerprint, completed=True)
            elif await _broadcast(targets, Message(_summary(match))):
                await update_state(match_id, fingerprint=fingerprint)
        except HltvError as exc:
            logger.warning("轮询 HLTV 赛事 %s 失败：%s", match_id, exc)
        except Exception:
            logger.exception("处理 HLTV 赛事订阅失败：%s", match_id)


async def poll_subscriptions() -> None:
    """轮询旧版单场订阅和新版赛事订阅。"""
    await _poll_legacy_matches()
    entries = await list_active_events()
    for event_id, entry in entries.items():
        try:
            await _poll_event_subscription(event_id, entry)
        except HltvError as exc:
            logger.warning("轮询 HLTV 赛事 %s 失败：%s", event_id, exc)
        except Exception:
            logger.exception("处理 HLTV 赛事订阅失败：%s", event_id)


async def render_and_subscribe_match(match: MatchData) -> MessageSegment | None:
    """为历史即时查询准备资源并渲染 Rating。"""
    if not match.has_stats:
        return None
    match = await enrich_match_assets(match)
    return await render_rating_card(match)
