"""订阅轮询和推送服务。"""

from __future__ import annotations

from collections.abc import Iterable

from nonebot import get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .assets import enrich_match_assets
from .client import HltvError, fetch_match
from .models import MatchData
from .render import render_rating_card
from .storage import list_active, update_state


def _summary(match: MatchData) -> str:
    scores = " : ".join(team.score or "-" for team in match.teams[:2])
    event = f" | {match.event_name}" if match.event_name else ""
    return f"CS赛事更新：{match.display_title} {scores}（{match.status_text or match.status}）{event}"


async def _send_to_target(
    bot: Bot,
    target: dict[str, str],
    message: Message,
) -> bool:
    kind = target.get("kind")
    target_id = target.get("id")
    if not target_id:
        return False
    if kind == "group":
        await bot.call_api("send_group_msg", group_id=int(target_id), message=message)
        return True
    elif kind == "private":
        await bot.call_api("send_private_msg", user_id=int(target_id), message=message)
        return True
    return False


def _available_bots() -> Iterable[Bot]:
    return [bot for bot in get_bots().values() if isinstance(bot, Bot)]


async def _broadcast(
    targets: list[dict[str, str]],
    message: Message,
    *,
    bot: Bot | None = None,
) -> bool:
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


async def poll_subscriptions() -> None:
    """轮询活动订阅并发送状态变化。"""
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
            else:
                if await _broadcast(targets, Message(_summary(match))):
                    await update_state(match_id, fingerprint=fingerprint)
        except HltvError as exc:
            logger.warning("轮询 HLTV 赛事 %s 失败：%s", match_id, exc)
        except Exception:
            logger.exception("处理 HLTV 赛事订阅失败：%s", match_id)


async def render_and_subscribe_match(match: MatchData) -> MessageSegment | None:
    """为即时查询准备资源并渲染 Rating；无统计数据时返回 None。"""
    if not match.has_stats:
        return None
    match = await enrich_match_assets(match)
    return await render_rating_card(match)
