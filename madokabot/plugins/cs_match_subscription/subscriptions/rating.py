"""赛事 Rating 卡片生成与查询结果组装。"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ..assets import enrich_match_assets
from ..models import MatchData
from ..render import render_rating_card
from ..subscriptions.notifications import MAP_LABELS, team_names


async def rating_message(
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
    first, second = team_names(match)
    for index, map_name in enumerate(map_names):
        image = await render_rating_card(match, map_name=map_name)
        label = MAP_LABELS[index] if index < len(MAP_LABELS) else str(index + 1)
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
    messages.append(Message([MessageSegment.text("总数据\n"), total_image]))
    return messages
