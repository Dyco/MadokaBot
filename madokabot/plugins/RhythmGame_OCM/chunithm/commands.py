"""中二节奏查分、账号绑定与资源更新。"""

import re

import httpx
from jinja2 import TemplateError
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot_plugin_alconna import Arparma, At, Match
from playwright.async_api import Error as BrowserError
from pydantic import ValidationError

from madokabot.core.messaging.response import respond

from ..bindings import bind_player, get_binding, unbind_player
from ..utils import display_time
from .client import get_b50, get_player, get_score
from .matchers import CHUNITHM_USAGE, cb50, chunithm
from .models import DIFFICULTIES, Player
from .render import render_b50, score_labels
from .resources import prepare_resources, update_all_resources


async def resolve_player(event: MessageEvent, target: Match[At | str]) -> Player:
    """解析中二目标，只读取中二绑定，不复用舞萌好友码。"""
    if target.available:
        value = target.result
        if isinstance(value, At):
            user_id = value.target
        else:
            identifier = value.strip()
            if not re.fullmatch(r"[0-9]+", identifier):
                raise ValueError("查询目标请填写 15 位中二好友码、QQ 号或 @用户。")
            if len(identifier) == 15:
                return await get_player(identifier)
            user_id = identifier
    else:
        user_id = event.get_user_id()
    friend_code = await get_binding(user_id, game="chunithm")
    return await get_player(friend_code or user_id, qq=friend_code is None)


@chunithm.handle()
async def handle_root(result: Arparma) -> None:
    """没有指定子命令时展示中二用法。"""
    if not result.subcommands:
        await chunithm.finish(CHUNITHM_USAGE)


@chunithm.assign("help")
async def handle_help() -> None:
    """展示中二指令与使用条件。"""
    await chunithm.finish(CHUNITHM_USAGE)


@chunithm.assign("b50")
async def handle_chu_b50(
    bot: Bot, event: MessageEvent, matcher: Matcher, target: Match[At | str]
) -> None:
    """处理主命令下的中二 B50。"""
    await send_b50(bot, event, matcher, target)


@cb50.handle()
async def handle_cb50(
    bot: Bot, event: MessageEvent, matcher: Matcher, target: Match[At | str]
) -> None:
    """处理中二 B50 快捷入口。"""
    await send_b50(bot, event, matcher, target)


async def send_b50(
    bot: Bot, event: MessageEvent, matcher: Matcher, target: Match[At | str]
) -> None:
    """使用公共表情回应查询，渲染完成后引用原消息仅回复中二成绩图片。"""
    await respond(bot, event)
    try:
        player = await resolve_player(event, target)
        bests = await get_b50(player.friend_code)
        catalog = await prepare_resources(player, bests)
        picture = await render_b50(player, bests, catalog)
    except ValidationError:
        logger.warning("LXNS 中二玩家或 B50 数据结构与预期不符")
        await matcher.finish("LXNS 中二数据格式异常，请联系管理员检查当前版本接口。")
    except ValueError as exc:
        await matcher.finish(str(exc))
    except (OSError, RuntimeError, TemplateError, BrowserError):
        logger.exception("中二 B50 图片生成失败")
        await matcher.finish("中二 B50 图片生成失败，请联系管理员检查资源与渲染环境。")
    await matcher.finish(picture, reply_message=True)


@chunithm.assign("info")
async def handle_info(event: MessageEvent, target: Match[At | str]) -> None:
    """查询中二玩家 Rating、等级、称号与同步时间。"""
    try:
        player = await resolve_player(event, target)
        text = (
            f"玩家：{player.name}\nRating：{player.rating:.4f}\n"
            f"等级：{player.level} · 转生 {player.reborn_count} 次\n"
            f"称号：{player.trophy.name if player.trophy else '无'}\n"
            f"OVER POWER：{player.over_power:.2f}（{player.over_power_progress:.2f}%）\n"
            f"总游玩次数：{player.total_play_count}\n"
            f"同步时间：{display_time(player.upload_time)}（上海时间）"
        )
    except ValidationError:
        await chunithm.finish("LXNS 中二玩家数据格式异常，请联系管理员。")
    except ValueError as exc:
        await chunithm.finish(str(exc))
    await chunithm.finish(text)


@chunithm.assign("bind")
async def handle_bind(event: MessageEvent, friend_code: Match[str]) -> None:
    """验证玩家存在后保存当前 QQ 的中二全局绑定。"""
    if not friend_code.available or not re.fullmatch(r"[0-9]{15}", friend_code.result):
        await chunithm.finish("请提供 15 位中二好友码。\n" + CHUNITHM_USAGE)
    try:
        player = await get_player(friend_code.result)
        await bind_player(event.get_user_id(), player.friend_code, game="chunithm")
    except ValidationError:
        await chunithm.finish("LXNS 中二玩家数据格式异常，绑定未保存。")
    except ValueError as exc:
        await chunithm.finish(str(exc))
    await chunithm.finish(f"已绑定中二玩家：{player.name}，Rating：{player.rating:.4f}。")


@chunithm.assign("unbind")
async def handle_unbind(event: MessageEvent) -> None:
    """仅解除机器人内的中二绑定，不修改舞萌绑定或 LXNS 账号。"""
    removed = await unbind_player(event.get_user_id(), game="chunithm")
    await chunithm.finish("已解除机器人内的中二绑定。" if removed else "你尚未在机器人内绑定中二账号。")


def parse_difficulty(value: str) -> int:
    """解析颜色、英文或数字难度，黑色对应 ULTIMA。"""
    levels = {
        "绿": 0, "basic": 0, "0": 0,
        "黄": 1, "advanced": 1, "1": 1,
        "红": 2, "expert": 2, "2": 2,
        "紫": 3, "master": 3, "3": 3,
        "黑": 4, "ultima": 4, "4": 4,
        "we": 5, "worldsend": 5, "world'send": 5, "5": 5,
    }
    level = levels.get(value.casefold().replace(" ", ""))
    if level is None:
        raise ValueError("难度使用绿／黄／红／紫／黑／WE，或 BASIC～ULTIMA、0～5。")
    return level


@chunithm.assign("score")
async def handle_score(
    event: MessageEvent, song_id: Match[int], difficulty: Match[str], target: Match[At | str]
) -> None:
    """查询指定中二曲目和难度，保留完整曲目 ID。"""
    if not song_id.available or not difficulty.available:
        await chunithm.finish(CHUNITHM_USAGE)
    try:
        if song_id.result <= 0:
            raise ValueError("曲目 ID 必须为正整数。")
        level = parse_difficulty(difficulty.result)
        player = await resolve_player(event, target)
        score = await get_score(player.friend_code, song_id.result, level)
        rank, clear, combo, chain = score_labels(score)
        text = (
            f"{player.name} · {score.song_name} (ID {score.id})\n"
            f"{DIFFICULTIES[score.level_index]} {score.level}\n"
            f"分数：{score.score:,} · {rank}\nRating：{score.rating:.4f}\n"
            f"OVER POWER：{score.over_power:.2f}\n通关：{clear}\n"
            f"连击／链条：{combo or '—'}／{chain or '—'}"
        )
    except ValidationError:
        await chunithm.finish("LXNS 中二成绩数据格式异常，请联系管理员。")
    except ValueError as exc:
        await chunithm.finish(str(exc))
    await chunithm.finish(text)


@chunithm.assign("update")
async def handle_update(bot: Bot, event: MessageEvent) -> None:
    """仅允许超级用户更新中二曲目快照和曲绘。"""
    if not await SUPERUSER(bot, event):
        await chunithm.finish("资源更新仅限机器人超级用户操作。")
    await respond(bot, event)
    try:
        result = await update_all_resources()
    except httpx.HTTPStatusError as exc:
        reason = "资源服务限流" if exc.response.status_code == 429 else "资源服务暂不可用"
        await chunithm.finish(f"{reason}，更新已停止；已下载文件保留，可稍后继续。")
    except (httpx.RequestError, OSError):
        logger.warning("中二资源更新因网络或文件读写失败中止")
        await chunithm.finish("中二资源更新中止，请检查网络和写入权限；已下载文件保留。")
    except ValueError as exc:
        await chunithm.finish(str(exc))
    await chunithm.finish(
        f"中二资源更新完成：曲目 {result['songs']}，保留曲绘 {result['existing']}，"
        f"补齐 {result['downloaded']}，远端未收录 {result['unavailable']}。"
    )
