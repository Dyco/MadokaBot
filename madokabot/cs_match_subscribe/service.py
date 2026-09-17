"""赛事订阅轮询和合并转发服务。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .assets import enrich_match_assets
from .client import HltvError, fetch_event, fetch_event_match_refs, fetch_match
from .config import config
from .models import (
    EVENT_STATUS_FINISHED,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_WAITING,
    EVENT_STATUSES,
    EventMatchRef,
    MapScore,
    MatchData,
)
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


def _map_start_message(
    match: MatchData,
    map_name: str,
    index: int,
    event_name: str = "",
) -> Message:
    """生成单张地图开始的合并转发文本节点。"""
    first, second = _team_names(match)
    label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
    event_prefix = f"【{event_name}】" if event_name else ""
    name_suffix = f"（{map_name}）" if map_name else ""
    return Message(
        MessageSegment.text(
            f"订阅赛事更新\n"
            f"{event_prefix}\n"
            f"{first} 对阵 {second} 的图{label}{name_suffix}开始"
        )
    )


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


def _started_map_candidates(match: MatchData) -> list[tuple[int, str]]:
    """返回 Scoreboard 标记且已有非零比分的地图。"""
    if not match.has_started:
        return []

    return [
        (index, result.name.strip())
        for index, result in enumerate(match.map_results)
        if result.is_live and result.is_started and not result.is_finished
    ]


def _parse_datetime(value: Any) -> datetime | None:
    """解析 JSON 中保存的 ISO 时间并统一为 UTC。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _event_status(entry: dict[str, Any]) -> str:
    """读取赛事订阅状态，并兼容旧版没有状态字段的记录。"""
    if entry.get("completed", False):
        return EVENT_STATUS_FINISHED
    status = str(entry.get("status", "")).strip()
    return status if status in EVENT_STATUSES else EVENT_STATUS_WAITING


def _event_start_at(entry: dict[str, Any]) -> datetime | None:
    """读取赛事官方开始时间，用于避免过早检查等待中的赛事。"""
    event_data = entry.get("event_data")
    if not isinstance(event_data, dict):
        return None
    return _parse_datetime(event_data.get("start_at"))


def _positive_score(value: str | None) -> bool:
    """判断比分是否已经出现非零回合或系列赛比分。"""
    try:
        return int(str(value).strip()) > 0
    except (TypeError, ValueError):
        return False


def _match_has_actual_start(match: MatchData) -> bool:
    """按实时地图非零比分判断一场比赛是否实际开始。"""
    if any(
        result.is_live and result.is_started and not result.is_finished
        for result in match.map_results
    ):
        return True
    return match.status == "live" and any(
        _positive_score(team.score) for team in match.teams[:2]
    )


def _all_matches_completed(matches: dict[str, Any]) -> bool:
    """判断赛事记录中的比赛是否全部完成。"""
    return bool(matches) and all(
        isinstance(state, dict) and state.get("completed", False)
        for state in matches.values()
    )


def _new_match_state(section: str, page_url: str = "") -> dict[str, Any]:
    """创建一场新发现比赛的轮询状态。"""
    return {
        "source": section,
        "url": page_url,
        "initialized": False,
        "historical": False,
        "started_sent": False,
        "final_sent": False,
        "completed": False,
        "map_scores": {},
        "started_maps": [],
        "notified_maps": [],
        "rating_maps": [],
        "rating_summary_sent": False,
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
    if map_name:
        if not match.has_map_rating(map_name):
            return None
    elif not match.has_total_rating:
        return None
    cache_key = map_name or "all"
    if cache_key not in cache:
        match = await enrich_match_assets(match)
        cache[cache_key] = await render_rating_card(match, map_name=map_name)
    return Message(cache[cache_key])


async def render_check_rating_messages(match: MatchData) -> list[Message]:
    """按比赛地图数量生成即时查询所需的 Rating 消息。"""
    if not match.has_stats or not match.rating_is_ready:
        return []

    match = await enrich_match_assets(match)
    map_names = match.rating_map_names

    if len(map_names) <= 1:
        map_name = map_names[0] if map_names else None
        return [Message(await render_rating_card(match, map_name=map_name))]

    messages: list[Message] = []
    first, second = _team_names(match)
    for index, map_name in enumerate(map_names):
        image = await render_rating_card(match, map_name=map_name)
        label = _MAP_LABELS[index] if index < len(_MAP_LABELS) else str(index + 1)
        score = next(
            (
                result.score_display.replace(":", "-")
                for result in match.map_results
                if result.name == map_name and result.is_finished
            ),
            "-",
        )
        messages.append(
            Message(
                [
                    MessageSegment.text(
                        f"图{label}（{map_name} {first} {score} {second}）\n"
                    ),
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
    push_each_map = bool(config.hltv_subscribe_push_each_map)
    previous_scores = state.get("map_scores")
    if not isinstance(previous_scores, dict):
        previous_scores = {}
    notified = state.get("notified_maps")
    if not isinstance(notified, list):
        notified = []
        state["notified_maps"] = notified
    notified_set = {str(value) for value in notified}
    rating_maps = state.get("rating_maps")
    if not isinstance(rating_maps, list):
        rating_maps = []
        state["rating_maps"] = rating_maps
    rating_set = {str(value) for value in rating_maps}
    if not initialized:
        previous_scores = _current_map_scores(match)

        # 订阅时已经结束的地图只建立基线，避免首次轮询补发历史开始通知。
        if push_each_map:
            started_maps = state.get("started_maps")
            if not isinstance(started_maps, list):
                started_maps = []
                state["started_maps"] = started_maps
            started_set = {str(value) for value in started_maps}
            for index, result in enumerate(match.map_results):
                if result.is_finished and result.is_started and str(index) not in started_set:
                    started_maps.append(str(index))
        # 订阅时已经结束的地图只建立消息和 Rating 基线，避免补发历史数据。
        for index, result in enumerate(match.map_results):
            if not result.is_finished:
                continue
            key = f"{index}:{result.name}"
            if key not in notified_set:
                notified.append(key)
                notified_set.add(key)
            if key not in rating_set:
                rating_maps.append(key)
                rating_set.add(key)

    if push_each_map:
        started_maps = state.get("started_maps")
        if not isinstance(started_maps, list):
            started_maps = []
            state["started_maps"] = started_maps
        started_set = {str(value) for value in started_maps}
        for index, map_name in _started_map_candidates(match):
            key = str(index)
            if key in started_set:
                continue
            messages.append(_map_start_message(match, map_name, index, event_name))
            started_maps.append(key)
            started_set.add(key)
        if match.has_started:
            # 保留该字段供旧版状态迁移和人工查看；每图模式的去重以
            # started_maps 为准。
            state["started_sent"] = True
    elif match.has_started and not state.get("started_sent", False):
        messages.append(_start_message(match, event_name))
        state["started_sent"] = True

    rating_cache: dict[str, MessageSegment] = {}
    current_scores = _current_map_scores(match)
    for index, result in enumerate(match.map_results):
        if not result.is_finished:
            continue
        key = f"{index}:{result.name}"
        score = result.score_display
        if push_each_map and key not in notified_set and previous_scores.get(key) != score:
            messages.append(_map_result_message(match, result, index))
            notified.append(key)
            notified_set.add(key)
        if push_each_map and key not in rating_set:
            image = await _rating_message(match, rating_cache, result.name)
            if image is not None:
                messages.append(image)
                rating_maps.append(key)
                rating_set.add(key)

    if match.is_finished:
        if not state.get("final_sent", False):
            messages.append(_final_message(match))
            state["final_sent"] = True
        if not state.get("rating_summary_sent", False):
            # 比赛结束和 Rating 生成不是同一时刻；没有完整 Rating 时保留
            # 赛事状态，下一次轮询继续尝试，不提前完成订阅。
            rating_messages = await render_check_rating_messages(match)
            if rating_messages:
                messages.extend(rating_messages)
                state["rating_summary_sent"] = True
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
                return ref, await fetch_match(
                    ref.match_id,
                    page_url=ref.url or None,
                )
            except HltvError as exc:
                logger.warning("轮询 HLTV 比赛 %s 失败：%s", ref.match_id, exc)
            except Exception:
                logger.exception("处理 HLTV 比赛订阅失败：%s", ref.match_id)
        return None

    results = await asyncio.gather(*(load(ref) for ref in refs))
    return [result for result in results if result is not None]


def _event_ended(entry: dict[str, Any]) -> bool:
    """判断赛事是否已经结束且所有比赛均已处理。"""
    end_at = _parse_datetime(entry.get("event_end"))
    if end_at is None:
        return False
    matches = entry.get("matches")
    return (
        isinstance(matches, dict)
        and end_at <= datetime.now(timezone.utc)
        and _all_matches_completed(matches)
    )


async def _activate_waiting_event(
    event_id: str,
    entry: dict[str, Any],
) -> bool:
    """检查等待赛事是否进入进行状态；等待时不请求比赛详情页。"""
    if _event_status(entry) != EVENT_STATUS_WAITING:
        return True

    now = datetime.now(timezone.utc)
    first_started_at = _parse_datetime(entry.get("first_match_started_at"))
    if first_started_at is not None:
        if first_started_at <= now:
            entry["status"] = EVENT_STATUS_ONGOING
            await update_event_state(event_id, status=EVENT_STATUS_ONGOING)
            return True
        return False

    scheduled_start = _event_start_at(entry)
    if scheduled_start is not None and scheduled_start > now:
        return False

    event = await fetch_event(event_id)
    if event.is_finished:
        entry["status"] = EVENT_STATUS_FINISHED
        entry["completed"] = True
        await update_event_state(
            event_id,
            status=EVENT_STATUS_FINISHED,
            completed=True,
        )
        return False
    status_is_live = event.event_status == "live"
    status_is_unknown_after_start = (
        event.event_status == "unknown"
        and event.start_at is not None
        and event.start_at <= now
    )
    if not (status_is_live or status_is_unknown_after_start):
        return False

    entry["status"] = EVENT_STATUS_ONGOING
    await update_event_state(event_id, status=EVENT_STATUS_ONGOING)
    return True


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
            if ref.url:
                state["url"] = ref.url
            if not state.get("completed", False):
                pending_refs.append(ref)
            continue
        if ref.section == "result" and ref.match_id in baseline_ids:
            matches[ref.match_id] = _historical_match_state()
            continue
        matches[ref.match_id] = _new_match_state(ref.section, ref.url)
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
                    url=str(state.get("url", "")),
                    section=str(state.get("source", "upcoming")),
                )
            )

    loaded = await _load_event_matches(pending_refs)
    messages: list[Message] = []
    event_name = str(entry.get("event_name", ""))
    observed_first_start: datetime | None = None
    for ref, match in loaded:
        if not _match_belongs_to_event(match, event_id, event_name):
            matches[ref.match_id] = _historical_match_state()
            continue
        state = matches[ref.match_id]
        if (
            observed_first_start is None
            and _match_has_actual_start(match)
        ):
            observed_first_start = (
                _parse_datetime(match.fetched_at)
                or datetime.now(timezone.utc)
            )
        messages.extend(await _process_event_match(match, state, event_name))

    targets = [
        target
        for target in entry.get("targets", [])
        if isinstance(target, dict)
    ]
    if messages:
        if not await _broadcast_forward(targets, messages):
            return

    first_started_at = entry.get("first_match_started_at")
    if observed_first_start is not None and not _parse_datetime(first_started_at):
        first_started_at = observed_first_start.isoformat()
        entry["first_match_started_at"] = first_started_at
        entry["status"] = EVENT_STATUS_ONGOING

    event_snapshot = {**entry, "matches": matches}
    event_finished = _event_ended(event_snapshot)
    status = EVENT_STATUS_FINISHED if event_finished else _event_status(entry)
    await update_event_state(
        event_id,
        matches=matches,
        status=status,
        first_match_started_at=(
            first_started_at if isinstance(first_started_at, str) else None
        ),
        completed=event_finished,
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
            if _event_status(entry) == EVENT_STATUS_WAITING:
                # 等待中的赛事只检查赛事状态，不抓取比赛详情页。
                if not await _activate_waiting_event(event_id, entry):
                    continue
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
