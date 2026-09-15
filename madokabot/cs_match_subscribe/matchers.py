"""CS/HLTV 指令注册。"""

from __future__ import annotations

from datetime import datetime, timezone
import re

from arclet.alconna import StrMulti
from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot_plugin_alconna import (
    Alconna,
    Args,
    Arparma,
    Match,
    Subcommand,
    on_alconna,
)
from nonebot_plugin_apscheduler import scheduler

from ..madoka_bundle.plugins.common import respond
from .assets import enrich_event_assets
from .client import (
    HltvError,
    fetch_event,
    fetch_event_match_refs,
    fetch_events,
    fetch_match,
    match_id_from_url,
)
from .config import config
from .models import EventData, EventMatchRef
from .player_stats import (
    PlayerStatsError,
    bind_player,
    fetch_player_stats,
    get_binding,
    login_pw,
    normalize_platform,
    platform_label,
    SUPPORTED_PLATFORM_TEXT,
    unbind_player,
)
from .render import render_event_list_card, render_player_stats_card
from .service import render_check_rating_messages, send_rating_forward
from .storage import subscribe_event, target_from_event

BOT_NAME = "圆香"
UNSUPPORTED_LINK_MESSAGE = f"{BOT_NAME}暂不支持此链接"
CS_BIND_USAGE = f"用法：CS bind <{SUPPORTED_PLATFORM_TEXT}> <用户昵称>"
CS_UNBIND_USAGE = f"用法：CS unbind <{SUPPORTED_PLATFORM_TEXT}>"
CS_LOGIN_USAGE = "用法：CS login <手机号> <验证码>"
CS_STATS_USAGE = f"用法：CS 战绩 [{SUPPORTED_PLATFORM_TEXT}] [用户昵称]"


def _event_schedule_text(event: EventData) -> str:
    """生成订阅成功消息中的赛事日期。"""
    if event.start_at is None:
        return "待定"

    def format_date(value: datetime) -> str:
        return f"{value.year}年{value.month}月{value.day}日"

    start_text = format_date(event.start_at)
    if event.end_at is None or event.end_at.date() == event.start_at.date():
        return start_text
    return f"{start_text} - {format_date(event.end_at)}"


def _event_is_finished(event: EventData, refs: list[EventMatchRef]) -> bool:
    """按赛事官方状态判断是否不可再订阅，并提供无状态时的兜底。"""
    if event.is_finished:
        return True
    if event.event_status != "unknown":
        return False

    # 页面没有状态标记时，如果所有已发现的比赛都来自 Results，且赛事
    # 结束时间已过，也视为已结束；存在 Live/Upcoming 比赛则允许订阅。
    if not refs or any(ref.section == "upcoming" for ref in refs):
        return False
    if event.end_at is None:
        return False
    end_at = event.end_at
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    return end_at <= datetime.now(timezone.utc)

CS_USAGE = """用法：
CS help
CS list event  列出当前及未来三个月的高奖金国际 LAN 和 Major 赛事
CS sub <赛事ID>  订阅赛事并推送其中的比赛结果
CS check <比赛链接>  查询一场比赛的 Rating
CS login <手机号> <验证码>  登录完美平台并保存 Session（验证码请自行获取）
CS bind <5E|5e|5eplay|wm|pw|完美> <用户昵称>  绑定平台战绩查询对象
CS unbind <5E|5e|5eplay|wm|pw|完美>  解除指定平台绑定
CS 战绩 [5E|5e|5eplay|wm|pw|完美] [用户昵称]  查询指定玩家或自己的绑定战绩
CS 5e [昵称]  查询 5E 聚合战绩
CS pw [昵称]  查询完美平台聚合战绩

示例：
CS sub 8057

订阅后，比赛开始、每张地图结束和系列赛结束会通过合并转发推送。"""


cs_command = Alconna(
    "cs",
    Subcommand("help", alias=["帮助"], help_text="查看 CS 赛事指令帮助"),
    Subcommand(
        "list",
        Args["params?", StrMulti],
        alias=["列表"],
        help_text="列出 CS 赛事信息",
    ),
    Subcommand(
        "sub",
        Args["event_id", StrMulti],
        alias=["订阅"],
        help_text="订阅 HLTV 赛事并推送其中的比赛结果",
    ),
    Subcommand(
        "login",
        Args["mobile?", str],
        Args["code?", str],
        alias=["登录"],
        help_text="使用手机号和验证码登录完美平台并保存 Session",
    ),
    Subcommand(
        "bind",
        # 合法平台继续使用二级子命令；可选参数负责接住空参数和未知平台，
        # 避免 Alconna 在解析阶段直接丢弃错误指令。
        Subcommand(
            "5e",
            Args["nickname?", StrMulti],
            alias=["5E", "5eplay", "5EPLAY"],
            help_text="绑定 5E 玩家昵称",
        ),
        Subcommand(
            "pw",
            Args["nickname?", StrMulti],
            alias=["PW", "wm", "WM", "完美"],
            help_text="绑定完美平台玩家昵称",
        ),
        Args["platform?", str],
        Args["nickname?", StrMulti],
        alias=["绑定"],
        help_text="绑定 5E 或完美平台玩家昵称",
    ),
    Subcommand(
        "unbind",
        Subcommand(
            "5e",
            alias=["5E", "5eplay", "5EPLAY"],
            help_text="解除 5E 绑定",
        ),
        Subcommand(
            "pw",
            alias=["PW", "wm", "WM", "完美", "完美世界"],
            help_text="解除完美平台绑定",
        ),
        Args["platform?", str],
        alias=["解绑"],
        help_text="解除指定平台绑定",
    ),
    Subcommand(
        "5e",
        Args["nickname?", StrMulti],
        alias=["5E", "5eplay", "5EPLAY", "5e战绩", "5e查询"],
        help_text="查询 5E 玩家战绩",
    ),
    Subcommand(
        "pw",
        Args["nickname?", StrMulti],
        alias=["PW", "wm", "WM", "完美", "完美战绩", "pw查询"],
        help_text="查询完美平台玩家战绩",
    ),
    Subcommand(
        "stats",
        Subcommand(
            "5e",
            Args["nickname?", StrMulti],
            alias=["5E", "5eplay", "5EPLAY"],
            help_text="查询 5E 战绩，可指定玩家昵称",
        ),
        Subcommand(
            "pw",
            Args["nickname?", StrMulti],
            alias=["PW", "wm", "WM", "完美"],
            help_text="查询完美平台战绩，可指定玩家昵称",
        ),
        Args["platform?", str],
        Args["nickname?", StrMulti],
        alias=["战绩", "查询战绩"],
        help_text="查询指定玩家或按绑定信息查询战绩",
    ),
    Subcommand(
        "check",
        Args["match_url?", StrMulti],
        alias=["查看"],
        help_text="查询 HLTV 比赛 Rating",
    ),
)

cs_cmd = on_alconna(
    cs_command,
    # 同时兼容项目默认的 / 前缀和直接输入 CS/cs。
    aliases={"CS", "/cs", "/CS"},
    use_cmd_start=False,
    priority=10,
    block=True,
)


@cs_cmd.handle()
async def handle_cs_root(result: Arparma) -> None:
    bind_result = result.subcommands.get("bind")
    if bind_result is not None and not bind_result.subcommands:
        await cs_cmd.finish(CS_BIND_USAGE)
    if not result.subcommands:
        await cs_cmd.finish(CS_USAGE)


@cs_cmd.assign("help")
async def handle_cs_help() -> None:
    await cs_cmd.finish(CS_USAGE)


@cs_cmd.assign("list")
async def handle_cs_list(params: Match[str]) -> None:
    """解析 list 的二级参数并执行对应查询。"""
    raw_params = params.result.strip() if params.available else ""
    list_args = raw_params.split()
    if len(list_args) != 1 or list_args[0].casefold() != "event":
        await cs_cmd.finish("用法：CS list event")

    try:
        events = await fetch_events()
        await enrich_event_assets(events)
        image = await render_event_list_card(events)
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV 赛事列表查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事列表查询失败")
        await cs_cmd.finish("HLTV 赛事列表处理失败，请稍后重试。")
        return
    await cs_cmd.finish(Message([image]))


def _normalize_mobile(value: str) -> str:
    """清理手机号输入，兼容用户复制时带入的空格或 +86 前缀。"""
    mobile = re.sub(r"\s+", "", value.strip())
    if mobile.startswith("+86"):
        mobile = mobile[3:]
    return mobile


@cs_cmd.assign("login")
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
    if not re.fullmatch(r"\d{4,8}", raw_code):
        await cs_cmd.finish("验证码格式不正确，请输入 4-8 位数字验证码。")
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
        "完美平台 Session 已保存，现可使用 CS pw 或 CS bind pw <昵称>。"
    )


async def _handle_cs_bind(
    event: MessageEvent,
    platform: str,
    nickname: Match[str],
) -> None:
    """保存当前 QQ 指定平台的查询绑定。"""
    raw_nickname = nickname.result.strip() if nickname.available else ""
    if not raw_nickname:
        await cs_cmd.finish(CS_BIND_USAGE)

    await cs_cmd.send(f"正在解析{platform_label(platform)}玩家 {raw_nickname}…")
    try:
        binding = await bind_player(str(event.user_id), platform, raw_nickname)
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"绑定失败：{exc}")
        return
    except Exception:
        logger.exception("CS 玩家绑定失败：platform=%s, nickname=%s", platform, nickname)
        await cs_cmd.finish("绑定失败，请稍后重试。")
        return

    if platform == "pw" and not binding.uuid:
        await cs_cmd.finish(
            f"已记录完美平台昵称：{binding.player_name}\n"
            "当前未获取到完美平台 SteamID，请稍后重试或使用 CS login <手机号> <验证码>。"
        )
        return
    await cs_cmd.finish(
        f"绑定成功：{platform_label(platform)} {binding.player_name}\n"
        f"平台 ID：{binding.domain or '-'}\n"
        f"账号 ID：{binding.uuid or '-'}"
    )


@cs_cmd.assign("bind.5e")
async def handle_cs_bind_5e(event: MessageEvent, nickname: Match[str]) -> None:
    """处理 5E 昵称绑定。"""
    await _handle_cs_bind(event, "5e", nickname)


@cs_cmd.assign("bind.pw")
async def handle_cs_bind_pw(event: MessageEvent, nickname: Match[str]) -> None:
    """处理完美平台昵称绑定。"""
    await _handle_cs_bind(event, "pw", nickname)


async def _handle_cs_unbind(event: MessageEvent, platform: str) -> None:
    """解除当前 QQ 用户指定平台的绑定。"""
    try:
        binding = unbind_player(str(event.user_id), platform)
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"解绑失败：{exc}")
        return

    if binding is None:
        await cs_cmd.finish(f"未找到{platform_label(platform)}绑定，无需解绑。")
        return
    await cs_cmd.finish(
        f"已解除{platform_label(platform)}绑定：{binding.player_name}\n"
        "平台 Session（如有）未受影响。"
    )


@cs_cmd.assign("unbind")
async def handle_cs_unbind(event: MessageEvent, platform: Match[str]) -> None:
    """处理解绑命令的显式平台参数。"""
    raw_platform = platform.result.strip() if platform.available else ""
    normalized = normalize_platform(raw_platform)
    if not raw_platform or normalized is None:
        await cs_cmd.finish(CS_UNBIND_USAGE)
        return
    await _handle_cs_unbind(event, normalized)


@cs_cmd.assign("unbind.5e")
async def handle_cs_unbind_5e(event: MessageEvent) -> None:
    """解除 5E 绑定。"""
    await _handle_cs_unbind(event, "5e")


@cs_cmd.assign("unbind.pw")
async def handle_cs_unbind_pw(event: MessageEvent) -> None:
    """解除完美平台绑定。"""
    await _handle_cs_unbind(event, "pw")


async def _handle_cs_player_stats(
    event: MessageEvent,
    platform: str,
    nickname: str = "",
) -> None:
    """读取绑定或昵称并渲染平台战绩卡片。"""
    raw_nickname = nickname.strip()
    if not raw_nickname and get_binding(str(event.user_id), platform) is None:
        await cs_cmd.finish(
            f"未绑定{platform_label(platform)}账号，请先使用 CS bind {platform} <昵称>"
        )

    target = raw_nickname or "已绑定账号"
    await cs_cmd.send(f"正在查询{platform_label(platform)}玩家 {target} 的战绩…")
    try:
        data = await fetch_player_stats(
            str(event.user_id),
            platform,
            raw_nickname,
        )
        image = await render_player_stats_card(data)
    except PlayerStatsError as exc:
        await cs_cmd.finish(f"查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 玩家战绩查询失败：platform=%s, nickname=%s", platform, raw_nickname)
        await cs_cmd.finish("战绩查询或图片渲染失败，请稍后重试。")
        return
    await cs_cmd.finish(Message([image]))


@cs_cmd.assign("5e")
async def handle_cs_5e(event: MessageEvent, nickname: Match[str]) -> None:
    """处理 5E 聚合战绩查询。"""
    await _handle_cs_player_stats(
        event,
        "5e",
        nickname.result.strip() if nickname.available else "",
    )


@cs_cmd.assign("pw")
async def handle_cs_pw(event: MessageEvent, nickname: Match[str]) -> None:
    """处理完美平台聚合战绩查询。"""
    await _handle_cs_player_stats(
        event,
        "pw",
        nickname.result.strip() if nickname.available else "",
    )


def _resolve_stats_platform(user_id: str, requested: str = "") -> str | None:
    """解析战绩查询平台；未指定时按完美世界、5E 的顺序选择绑定。"""
    raw_requested = requested.strip()
    if raw_requested:
        return normalize_platform(raw_requested)
    if get_binding(user_id, "pw") is not None:
        return "pw"
    if get_binding(user_id, "5e") is not None:
        return "5e"
    return None


def _stats_requested_platform(result: Arparma) -> str:
    """读取战绩命令中的显式平台，包括嵌套的 5e/pw 子命令。"""
    stats_result = result.subcommands.get("stats")
    if stats_result is None:
        return ""

    # `/cs 战绩 5e` 和 `/cs 战绩 完美` 会被 Alconna 解析为二级子命令，
    # 不能只依赖 Match[str] 查找名为 platform 的普通参数。
    if "5e" in stats_result.subcommands:
        return "5e"
    if "pw" in stats_result.subcommands:
        return "pw"

    raw_platform = stats_result.args.get("platform")
    return str(raw_platform).strip() if raw_platform is not None else ""


def _stats_requested_nickname(result: Arparma) -> str:
    """读取战绩命令中的可选玩家昵称。"""
    stats_result = result.subcommands.get("stats")
    if stats_result is None:
        return ""

    for platform in ("5e", "pw"):
        platform_result = stats_result.subcommands.get(platform)
        if platform_result is not None:
            raw_nickname = platform_result.args.get("nickname")
            return str(raw_nickname).strip() if raw_nickname is not None else ""

    raw_nickname = stats_result.args.get("nickname")
    return str(raw_nickname).strip() if raw_nickname is not None else ""


@cs_cmd.assign("stats")
async def handle_cs_stats(event: MessageEvent, result: Arparma) -> None:
    """根据显式平台或用户绑定信息查询统一战绩。"""
    raw_platform = _stats_requested_platform(result)
    raw_nickname = _stats_requested_nickname(result)
    selected_platform = _resolve_stats_platform(str(event.user_id), raw_platform)
    if raw_platform and selected_platform is None:
        await cs_cmd.finish(CS_STATS_USAGE)
        return

    if selected_platform is None:
        await cs_cmd.finish(
            f"尚未绑定平台，请先使用 CS bind <{SUPPORTED_PLATFORM_TEXT}> <用户昵称>"
        )
        return

    await _handle_cs_player_stats(event, selected_platform, raw_nickname)


@cs_cmd.assign("stats.5e")
async def handle_cs_stats_5e(event: MessageEvent, nickname: Match[str]) -> None:
    """处理统一战绩查询中的 5E 平台参数。"""
    await _handle_cs_player_stats(
        event,
        "5e",
        nickname.result.strip() if nickname.available else "",
    )


@cs_cmd.assign("stats.pw")
async def handle_cs_stats_pw(event: MessageEvent, nickname: Match[str]) -> None:
    """处理统一战绩查询中的完美平台参数。"""
    await _handle_cs_player_stats(
        event,
        "pw",
        nickname.result.strip() if nickname.available else "",
    )


@cs_cmd.assign("check")
async def handle_cs_check(
    bot: Bot,
    event: MessageEvent,
    match_url: Match[str],
) -> None:
    """解析比赛链接并发送单图或合并转发 Rating。"""
    await respond(bot, event)
    raw_url = match_url.result.strip() if match_url.available else ""
    match_id = match_id_from_url(raw_url) if len(raw_url.split()) == 1 else None
    if match_id is None:
        await cs_cmd.finish(UNSUPPORTED_LINK_MESSAGE)
        return

    try:
        match = await fetch_match(match_id, page_url=raw_url)
        messages = await render_check_rating_messages(match)
    except HltvError as exc:
        logger.warning("CS 比赛链接解析失败：%s (%s)", raw_url, exc)
        await cs_cmd.finish(f"HLTV 查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 比赛 Rating 查询失败：%s", raw_url)
        await cs_cmd.finish("HLTV 查询或图片渲染失败，请稍后重试。")
        return

    if not messages:
        await cs_cmd.finish("没有解析到可用的比赛 Rating 数据。")
        return
    if len(messages) == 1:
        await cs_cmd.finish(messages[0])
        return

    target = target_from_event(event)
    if target is None or not await send_rating_forward(bot, target, messages):
        await cs_cmd.finish("合并消息发送失败，请稍后重试。")
        return
    await cs_cmd.finish()


@cs_cmd.assign("sub")
async def handle_cs_sub(event: MessageEvent, event_id: Match[str]) -> None:
    raw_id = event_id.result.strip() if event_id.available else ""
    if not raw_id.isdigit():
        await cs_cmd.finish("赛事 ID 无效，请使用数字，例如：CS sub 8057")

    target = target_from_event(event)
    if target is None:
        await cs_cmd.finish("无法识别当前会话，暂时不能建立赛事订阅。")

    await cs_cmd.send("正在获取 HLTV 赛事信息并记录比赛列表…")
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
            event_name=event_data.name,
            event_url=event_data.url,
            event_end=event_data.end_at.isoformat() if event_data.end_at else "",
            match_refs=[
                {
                    "match_id": ref.match_id,
                    "url": ref.url,
                    "section": ref.section,
                }
                for ref in refs
            ],
        )
    except Exception:
        logger.exception("CS 赛事订阅失败：%s", raw_id)
        await cs_cmd.finish("HLTV 赛事订阅处理失败，请稍后重试。")
        return

    prefix = "已成功订阅赛事" if added else "已刷新赛事订阅"
    push_mode = (
        "每张地图开始、结束时单独推送，并在整场结束时补发完整 Rating 汇总"
        if config.hltv_subscribe_push_each_map
        else "按系列赛级别推送开始和结束，整场结束时补发完整 Rating 汇总"
    )
    await cs_cmd.finish(
        f"{prefix} {event_data.name}，赛程时间为{_event_schedule_text(event_data)}\n"
        f"已记录 {len(refs)} 场比赛，轮询间隔为{config.hltv_poll_interval}秒；"
        f"{push_mode}。"
    )


@scheduler.scheduled_job(
    "interval",
    seconds=config.hltv_poll_interval,
    id="madokabot_cs_match_subscribe_poll",
    max_instances=1,
    coalesce=True,
)
async def _poll_cs_match_subscriptions() -> None:
    from .service import poll_subscriptions

    await poll_subscriptions()
