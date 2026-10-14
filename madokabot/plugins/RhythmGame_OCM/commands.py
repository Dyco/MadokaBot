"""舞萌查分、绑定与资源更新的会话处理。"""

import math
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

from .bindings import bind_player, get_binding, unbind_player
from .client import get_b50, get_player, get_score
from .matchers import MAIMAI_USAGE, b50, maimai
from .models import DIFFICULTIES, Player
from .render import render_b50, score_labels
from .resources import prepare_resources, update_all_resources
from .utils import display_time


async def resolve_player(event: MessageEvent, target: Match[At | str]) -> Player:
    """解析查询目标，15 位数字视为好友码，其余数字按 QQ 查询。"""
    if target.available:
        value = target.result
        if isinstance(value, At):
            user_id = value.target
        else:
            identifier = value.strip()
            if not re.fullmatch(r"[0-9]+", identifier):
                raise ValueError("查询目标请填写 15 位好友码、QQ 号或 @用户。")
            if len(identifier) == 15:
                return await get_player(identifier)
            user_id = identifier
    else:
        user_id = event.get_user_id()
    friend_code = await get_binding(user_id)
    return await get_player(friend_code or user_id, qq=friend_code is None)


@maimai.handle()
async def handle_root(result: Arparma) -> None:
    """没有指定子命令时展示舞萌用法。"""
    if not result.subcommands:
        await maimai.finish(MAIMAI_USAGE)


@maimai.assign("help")
async def handle_help() -> None:
    """展示舞萌指令与权限说明。"""
    await maimai.finish(MAIMAI_USAGE)


@maimai.assign("b50")
async def handle_mai_b50(
    event: MessageEvent, matcher: Matcher, target: Match[At | str]
) -> None:
    """处理舞萌主命令下的 B50 查询。"""
    await send_b50(event, matcher, target)


@b50.handle()
async def handle_b50(
    event: MessageEvent, matcher: Matcher, target: Match[At | str]
) -> None:
    """处理独立的 B50 快捷命令。"""
    await send_b50(event, matcher, target)


async def send_b50(
    event: MessageEvent, matcher: Matcher, target: Match[At | str]
) -> None:
    """获取玩家 Best 50，准备本地素材后发送成绩图片。"""
    try:
        player = await resolve_player(event, target)
        bests = await get_b50(player.friend_code)
        await matcher.send("正在生成 B50，首次补齐素材可能需要稍等。")
        catalog = await prepare_resources(player, bests)
        picture = await render_b50(player, bests, catalog)
    except ValidationError:
        logger.warning("LXNS 玩家或成绩数据结构与预期不符")
        await matcher.finish("LXNS 返回的成绩数据格式异常，请联系管理员。")
    except ValueError as exc:
        await matcher.finish(str(exc))
    except (OSError, RuntimeError, TemplateError, BrowserError):
        logger.exception("舞萌 B50 图片生成失败")
        await matcher.finish("B50 图片生成失败，请联系管理员检查资源与渲染环境。")
    await matcher.finish(picture)


@maimai.assign("info")
async def handle_info(event: MessageEvent, target: Match[At | str]) -> None:
    """查询玩家名称、Rating、称号和最近同步时间。"""
    try:
        player = await resolve_player(event, target)
        text = (
            f"玩家：{player.name}\nDX Rating：{player.rating}\n"
            f"称号：{player.trophy.name if player.trophy else '无'}\n"
            f"搭档觉醒数：{player.star}\n"
            f"同步时间：{display_time(player.upload_time)}（上海时间）"
        )
    except ValidationError:
        await maimai.finish("LXNS 玩家数据格式异常，请联系管理员。")
    except ValueError as exc:
        await maimai.finish(str(exc))
    await maimai.finish(text)


@maimai.assign("bind")
async def handle_bind(event: MessageEvent, friend_code: Match[str]) -> None:
    """验证好友码后保存当前 QQ 的全局绑定。"""
    if not friend_code.available or not re.fullmatch(r"[0-9]{15}", friend_code.result):
        await maimai.finish("请提供 15 位舞萌好友码。\n" + MAIMAI_USAGE)
    try:
        player = await get_player(friend_code.result)
        await bind_player(event.get_user_id(), player.friend_code)
    except ValidationError:
        await maimai.finish("LXNS 玩家数据格式异常，绑定未保存。")
    except ValueError as exc:
        await maimai.finish(str(exc))
    await maimai.finish(f"已绑定舞萌玩家：{player.name}，DX Rating：{player.rating}。")


@maimai.assign("unbind")
async def handle_unbind(event: MessageEvent) -> None:
    """解除当前 QQ 在机器人内的绑定，不修改 LXNS 账号。"""
    removed = await unbind_player(event.get_user_id())
    await maimai.finish("已解除机器人内的舞萌绑定。" if removed else "你尚未在机器人内绑定舞萌账号。")


def parse_chart(song_id: int, difficulty: str, chart_type: str) -> tuple[int, int, str]:
    """识别颜色或英文难度，并规范标准与 DX 曲目 ID。"""
    levels = {
        "绿": 0, "basic": 0, "0": 0,
        "黄": 1, "advanced": 1, "1": 1,
        "红": 2, "expert": 2, "2": 2,
        "紫": 3, "master": 3, "3": 3,
        "白": 4, "remaster": 4, "re:master": 4, "4": 4,
    }
    types = {"sd": "standard", "standard": "standard", "标准": "standard", "dx": "dx"}
    level = levels.get(difficulty.casefold())
    song_type = types.get(chart_type.casefold())
    if level is None or song_type is None:
        raise ValueError("难度使用绿／黄／红／紫／白或 0～4，谱面类型使用 SD／DX。")
    if not 0 < song_id < 100000:
        raise ValueError("请提供有效的普通曲目 ID，暂不支持宴会场成绩查询。")
    return song_id % 10000, level, song_type


@maimai.assign("score")
async def handle_score(
    event: MessageEvent, song_id: Match[int], difficulty: Match[str],
    chart_type: Match[str], target: Match[At | str],
) -> None:
    """查询指定曲目、难度和谱面类型的最佳成绩。"""
    if not all(item.available for item in (song_id, difficulty, chart_type)):
        await maimai.finish(MAIMAI_USAGE)
    try:
        identifier, level, song_type = parse_chart(song_id.result, difficulty.result, chart_type.result)
        player = await resolve_player(event, target)
        score = await get_score(player.friend_code, identifier, level, song_type)
        rate, fc, fs = score_labels(score)
        text = (
            f"{player.name} · {score.song_name} (ID {score.id})\n"
            f"{'DX' if score.type == 'dx' else 'SD'} · {DIFFICULTIES[score.level_index]} {score.level}\n"
            f"达成率：{score.achievements:.4f}% · {rate}\n"
            f"Rating：{math.floor(score.dx_rating)}\nDX 分数：{score.dx_score} · ★{score.dx_star}\n"
            f"连击／同步：{fc or '—'}／{fs or '—'}"
        )
    except ValidationError:
        await maimai.finish("LXNS 成绩数据格式异常，请联系管理员。")
    except ValueError as exc:
        await maimai.finish(str(exc))
    await maimai.finish(text)


@maimai.assign("update")
async def handle_update(bot: Bot, event: MessageEvent) -> None:
    """仅允许超级用户更新公共曲目快照并增量补齐曲绘。"""
    if not await SUPERUSER(bot, event):
        await maimai.finish("资源更新仅限机器人超级用户操作。")
    await maimai.send("开始增量更新舞萌资源，已有曲绘会保留，下载按间隔限速。")
    try:
        result = await update_all_resources()
    except httpx.HTTPStatusError as exc:
        message = "资源服务限流" if exc.response.status_code == 429 else "资源服务暂不可用"
        await maimai.finish(f"{message}，本次更新已停止；已下载资源保留，可稍后重新执行。")
    except (httpx.RequestError, OSError):
        logger.warning("舞萌资源更新因网络或文件读写失败中止")
        await maimai.finish("资源更新中止，请检查网络和目录写入权限；已下载文件保留。")
    except ValueError as exc:
        await maimai.finish(str(exc))
    await maimai.finish(
        f"舞萌资源更新完成：曲目 {result['songs']}，保留曲绘 {result['existing']}，"
        f"补齐 {result['downloaded']}，远端未收录 {result['unavailable']}。"
    )
