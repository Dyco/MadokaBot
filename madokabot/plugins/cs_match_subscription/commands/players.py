"""CS 玩家登录、绑定、解绑和战绩命令。"""

from __future__ import annotations

import re

from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot_plugin_alconna import Match

from ..matchers import (
    CS_BIND_USAGE,
    CS_LOGIN_USAGE,
    CS_STATS_USAGE,
    CS_UNBIND_USAGE,
    cs_cmd,
)
from ..players.models import PlayerStatsError
from ..players.perfect_world import login_pw
from ..players.platforms import normalize_platform, platform_label
from ..players.service import bind_player, fetch_player_stats, unbind_player
from ..render import render_player_stats_card


def _normalize_mobile(value: str) -> str:
    """清理手机号输入，兼容用户复制时带入的空格或 +86 前缀。"""
    mobile = re.sub(r"\s+", "", value.strip())
    if mobile.startswith("+86"):
        mobile = mobile[3:]
    return mobile


@cs_cmd.assign("subcommands.login")
async def handle_cs_login(
    bot: Bot,
    event: MessageEvent,
    mobile: Match[str],
    code: Match[str],
) -> None:
    """使用用户自行获取的验证码登录，并保存返回的 Session。"""
    if isinstance(event, GroupMessageEvent):
        try:
            await bot.delete_msg(message_id=event.message_id)
        except Exception as exc:
            logger.warning("CS 登录指令撤回失败：%s", exc)
    elif not isinstance(event, PrivateMessageEvent):
        await cs_cmd.finish("此功能仅支持私聊或群聊消息")
        return

    raw_mobile = _normalize_mobile(mobile.result if mobile.available else "")
    if not re.fullmatch(r"1\d{10}", raw_mobile):
        await cs_cmd.finish(CS_LOGIN_USAGE)
        return

    raw_code = code.result.strip() if code.available else ""
    if not raw_code:
        await cs_cmd.finish(CS_LOGIN_USAGE)
        return
    if not re.fullmatch(r"\d{6}", raw_code):
        await cs_cmd.finish("验证码格式不正确，请输入6位数字验证码。")
        return

    await cs_cmd.send("正在登录完美平台并保存 Session…")
    try:
        account_info = await login_pw(raw_mobile, raw_code)
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"登录失败：{exc}")
        return
    except Exception:
        logger.exception("CS 完美平台登录失败：mobile=%s", raw_mobile)
        await cs_cmd.finish("登录失败，请稍后重试。")
        return

    nickname = str(
        account_info.get("nickname")
        or account_info.get("nickName")
        or account_info.get("username")
        or "未知用户"
    ).strip()
    await cs_cmd.finish(
        f"登录成功，欢迎回来，{nickname}。\n"
        "完美平台 Session 已保存，现可使用 CS 战绩 pw 或 CS bind pw [Steam 32 位或 64 位 ID]。"
    )


async def _handle_cs_bind(
    event: MessageEvent,
    platform: str,
    player: str,
) -> None:
    """保存当前 QQ 指定平台的查询绑定。"""
    identifier = player.strip()
    if not identifier and platform != "pw":
        await cs_cmd.finish(CS_BIND_USAGE)

    target = "玩家昵称" if platform == "5e" else "Steam ID"
    target_value = identifier or "已有全局绑定"
    await cs_cmd.send(f"正在绑定{platform_label(platform)}{target} {target_value}…")
    try:
        binding = await bind_player(
            str(event.user_id), platform, identifier, event.sender.nickname or ""
        )
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"绑定失败：{exc}")
        return
    except Exception:
        logger.exception("CS 玩家绑定失败：platform=%s, player=%s", platform, player)
        await cs_cmd.finish("绑定失败，请稍后重试。")
        return

    if platform == "pw":
        await cs_cmd.finish(
            f"绑定成功：{platform_label(platform)}\n"
            f"Steam 64 位 ID：{binding.uuid}\n"
            "此绑定与 Steam 共用；如需群播报，请在目标群使用 steam bind。"
        )
        return
    await cs_cmd.finish(
        f"绑定成功：{platform_label(platform)} {binding.player_name}\n"
        f"平台 ID：{binding.domain or '-'}\n"
        f"账号 ID：{binding.uuid or '-'}"
    )


@cs_cmd.assign("subcommands.bind")
async def handle_cs_bind(event: MessageEvent, params: Match[str]) -> None:
    """解析平台和玩家昵称或 Steam ID 后执行绑定。"""
    raw_params = params.result.strip() if params.available else ""
    bind_args = raw_params.split(maxsplit=1)
    if not 1 <= len(bind_args) <= 2:
        await cs_cmd.finish(CS_BIND_USAGE)
        return

    platform = normalize_platform(bind_args[0])
    if platform is None or (platform == "5e" and len(bind_args) != 2):
        await cs_cmd.finish(CS_BIND_USAGE)
        return
    await _handle_cs_bind(event, platform, bind_args[1] if len(bind_args) == 2 else "")


async def _handle_cs_unbind(event: MessageEvent, platform: str) -> None:
    """解除当前 QQ 用户指定平台的绑定。"""
    try:
        binding = await unbind_player(str(event.user_id), platform)
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"解绑失败：{exc}")
        return
    except Exception:
        logger.exception("CS 玩家解绑失败：platform=%s", platform)
        await cs_cmd.finish("解绑失败，请稍后重试。")
        return

    if binding is None:
        await cs_cmd.finish(f"未找到{platform_label(platform)}绑定，无需解绑。")
        return
    if platform == "pw":
        await cs_cmd.finish(
            f"已解除 Steam/CS 共用绑定：{binding.uuid}。"
            "Steam 各群订阅已一并删除；完美平台 Session 未受影响。"
        )
        return
    await cs_cmd.finish(
        f"已解除{platform_label(platform)}绑定：{binding.player_name}\n"
        "平台 Session（如有）未受影响。"
    )


@cs_cmd.assign("subcommands.unbind")
async def handle_cs_unbind(event: MessageEvent, params: Match[str]) -> None:
    """解析平台参数后执行解绑。"""
    raw_platform = params.result.strip() if params.available else ""
    if len(raw_platform.split()) != 1:
        await cs_cmd.finish(CS_UNBIND_USAGE)
        return
    normalized = normalize_platform(raw_platform)
    if not raw_platform or normalized is None:
        await cs_cmd.finish(CS_UNBIND_USAGE)
        return
    await _handle_cs_unbind(event, normalized)


async def _handle_cs_player_stats(
    event: MessageEvent,
    platform: str,
    nickname: str = "",
) -> None:
    """读取绑定或指定昵称，并渲染平台战绩卡片。"""
    target = nickname.strip()
    target_text = f"玩家 {target}" if target else "已绑定玩家"
    await cs_cmd.send(f"正在查询{platform_label(platform)}{target_text}的战绩…")
    try:
        data = await fetch_player_stats(str(event.user_id), platform, target)
        image = await render_player_stats_card(data)
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 玩家战绩查询失败：platform=%s", platform)
        await cs_cmd.finish("战绩查询或图片渲染失败，请稍后重试。")
        return
    await cs_cmd.finish(Message([image]))


@cs_cmd.assign("subcommands.result")
async def handle_cs_stats(
    event: MessageEvent,
    platform: Match[str],
    nickname: Match[str],
) -> None:
    """根据平台及可选昵称查询玩家战绩。"""
    raw_platform = platform.result.strip() if platform.available else ""
    selected_platform = normalize_platform(raw_platform)
    if not raw_platform or selected_platform is None:
        await cs_cmd.finish(CS_STATS_USAGE)
        return
    target = nickname.result.strip() if nickname.available else ""
    await _handle_cs_player_stats(event, selected_platform, target)
