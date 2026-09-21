"""CS/HLTV 指令注册。"""

from __future__ import annotations

from datetime import datetime, timezone
import re

from arclet.alconna import StrMulti
from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GROUP_ADMIN,
    GROUP_OWNER,
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.permission import SUPERUSER
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
from .models import (
    EVENT_STATUS_FINISHED,
    MATCH_SECTION_UPCOMING,
    EventData,
    EventMatchRef,
)
from .player_stats import (
    PlayerStatsError,
    bind_player,
    fetch_player_stats,
    login_pw,
    normalize_platform,
    platform_label,
    SUPPORTED_PLATFORM_TEXT,
    unbind_player,
)
from .prediction import (
    PredictionError,
    get_prediction_detail,
    get_prediction_ranking,
    place_prediction,
)
from .render import (
    render_event_list_card,
    render_player_stats_card,
    render_prediction_rank_card,
)
from .service import render_check_rating_messages, send_rating_forward
from .storage import (
    add_event_target_if_exists,
    get_hltv_event_settings,
    remove_event_subscription,
    set_hltv_event_push_each_map,
    subscribe_event,
    target_from_event,
    toggle_hltv_event_prediction,
    toggle_hltv_event_start_notification,
    unsubscribe_all_events,
    unsubscribe_event,
)

BOT_NAME = "圆香"
UNSUPPORTED_LINK_MESSAGE = f"{BOT_NAME}暂不支持此链接"
CS_BIND_USAGE = f"用法：CS bind <{SUPPORTED_PLATFORM_TEXT}> <用户昵称>"
CS_UNBIND_USAGE = f"用法：CS unbind <{SUPPORTED_PLATFORM_TEXT}>"
CS_LOGIN_USAGE = "用法：CS login <手机号> <验证码>"
CS_STATS_USAGE = f"用法：CS 战绩 <{SUPPORTED_PLATFORM_TEXT}> [玩家昵称]"
CS_UNSUB_USAGE = "用法：CS unsub <赛事ID>"
CS_REMOVESUB_USAGE = "用法：CS removesub <赛事ID>"
CS_EVENT_USAGE = "用法：CS event <all|single|notif|predict>"
CS_PREDICTION_USAGE = (
    "用法：\n"
    "CS prediction <队伍名|A/B> <积分>\n"
    "CS prediction rank <本群|全部>"
)

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
    # 结束时间已过，也视为已结束；存在 live 比赛则允许订阅。
    if not refs or any(ref.section == MATCH_SECTION_UPCOMING for ref in refs):
        return False
    if event.end_at is None:
        return False
    end_at = event.end_at
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    return end_at <= datetime.now(timezone.utc)


async def _group_subscription_target(
    bot: Bot,
    event: MessageEvent,
) -> dict[str, str] | None:
    """校验群管理权限并返回当前群的推送目标。"""
    if not isinstance(event, GroupMessageEvent):
        await cs_cmd.finish("此命令仅支持群聊。")
        return None
    if not (
        await SUPERUSER(bot, event)
        or await GROUP_ADMIN(bot, event)
        or await GROUP_OWNER(bot, event)
    ):
        await cs_cmd.finish("权限不足，只有超级用户、群管理员或群主可以使用此命令。")
        return None
    return {"kind": "group", "id": str(event.group_id)}


CS_USAGE = """用法：
CS help
CS list event  列出当前及未来三个月的高奖金国际 LAN 和 Major 赛事
CS list <比赛ID> 查看竞猜情况
CS sub <赛事ID>  订阅赛事并推送其中的比赛结果
CS event <all|single|notif|predict> 设置本群推送方式、开赛提醒和竞猜
CS unsub <赛事ID>  本群退订指定赛事推送
CS nosub  本群退订全部赛事推送
CS removesub <赛事ID>  超级用户全局移除赛事订阅
CS check <比赛链接>  查询一场比赛的 Rating
CS prediction <队伍名|A/B> <积分> 参与当前比赛竞猜
CS prediction rank <本群|全部> 查看竞猜排行榜
CS login <手机号> <验证码>  登录完美平台并保存 Session（验证码请自行获取）
CS bind <5E|5e|5eplay|wm|pw|完美> <用户昵称>  绑定平台战绩查询对象
CS unbind <5E|5e|5eplay|wm|pw|完美>  解除指定平台绑定
CS result <5E|5e|5eplay|wm|pw|完美> [玩家昵称]  查询绑定账号或指定玩家的战绩


订阅后的推送方式和赛事开始通知，按本群的CS event设置生效。"""


cs_command = Alconna(
    "cs",
    Subcommand(
        "help",
        alias=["帮助"],
        help_text="查看 CS 赛事指令帮助",
    ),
    Subcommand(
        "list",
        Args["params?", StrMulti],
        alias=["列表"],
        help_text="列出 CS 赛事信息或查看竞猜情况",
    ),
    Subcommand(
        "event",
        Args["params?", StrMulti],
        alias=["赛事", "比赛"],
        help_text="设置本群赛事推送方式",
    ),
    Subcommand(
        "prediction",
        Args["params?", StrMulti],
        alias=["竞猜", "预测"],
        help_text="参与赛事预测",
    ),
    Subcommand(
        "sub",
        Args["event_id?", StrMulti],
        alias=["订阅"],
        help_text="订阅 HLTV 赛事并推送其中的比赛结果",
    ),
    Subcommand(
        "unsub",
        Args["event_id?", str],
        alias=["退订"],
        help_text="让当前群退订指定赛事推送",
    ),
    Subcommand(
        "nosub",
        alias=["退订全部", "退订所有"],
        help_text="让当前群退订全部赛事推送",
    ),
    Subcommand(
        "removesub",
        Args["event_id?", str],
        alias=["移除订阅", "删除订阅"],
        help_text="超级用户全局移除指定赛事订阅",
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
        Args["params?", StrMulti],
        alias=["绑定"],
        help_text="绑定 5E 或完美平台玩家昵称",
    ),
    Subcommand(
        "unbind",
        Args["params?", StrMulti],
        alias=["解绑"],
        help_text="解除指定平台绑定",
    ),
    Subcommand(
        "result",
        Args["platform", str],
        Args["nickname?", StrMulti],
        alias=["战绩"],
        help_text="查询指定平台上已绑定的玩家或其他玩家战绩",
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
    aliases={"CS"},
    priority=10,
    block=True,
)


@cs_cmd.handle()
async def handle_cs_root(result: Arparma) -> None:
    if not result.subcommands:
        await cs_cmd.finish(CS_USAGE)


@cs_cmd.assign("subcommands.help")
async def handle_cs_help() -> None:
    await cs_cmd.finish(CS_USAGE)


@cs_cmd.assign("subcommands.list")
async def handle_cs_list(
    event: MessageEvent,
    params: Match[str],
) -> None:
    """解析 list 的二级参数并执行对应查询。"""
    raw_params = params.result.strip() if params.available else ""
    list_args = raw_params.split()
    if len(list_args) == 1 and list_args[0].isdigit():
        if not isinstance(event, GroupMessageEvent):
            await cs_cmd.finish("竞猜功能仅支持群聊。")
            return
        try:
            detail = await get_prediction_detail(
                str(event.group_id),
                list_args[0],
            )
        except Exception:
            logger.exception(
                "CS 竞猜详情查询失败：group_id=%s match_id=%s",
                event.group_id,
                list_args[0],
            )
            await cs_cmd.finish("竞猜详情查询失败，请稍后重试。")
            return
        if detail is None:
            await cs_cmd.finish("未找到本群可查看的竞猜比赛。")
            return
        team_names = detail["team_names"]
        first = team_names[0] if len(team_names) > 0 else "队伍A"
        second = team_names[1] if len(team_names) > 1 else "队伍B"
        teams = detail["summary"]["teams"]
        first_summary = teams.get(first, {})
        second_summary = teams.get(second, {})
        lines = [
            f"【比赛编号：{detail['match_id']}】",
            f"{first}对阵{second}，{detail['status']}。",
            f"{first}：{first_summary.get('count', 0)}人预测，共计"
            f"{first_summary.get('points', 0)}积分。",
            f"{second}：{second_summary.get('count', 0)}人预测，共计"
            f"{second_summary.get('points', 0)}积分。",
        ]
        if detail["winner_name"]:
            lines.append(
                f"获胜队伍：{detail['winner_name']}（每人获得"
                f"{detail['payout_per_winner']}积分）"
            )
        await cs_cmd.finish("\n".join(lines))
        return

    if len(list_args) != 1 or list_args[0].casefold() != "event":
        await cs_cmd.finish("用法：CS list event | <比赛ID>")
        return

    try:
        events = await fetch_events()
        await enrich_event_assets(events)
        image = await render_event_list_card(events)
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV赛事列表查询失败，请之后重试：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事列表查询失败")
        await cs_cmd.finish("HLTV赛事列表处理失败，请稍后重试。")
        return
    await cs_cmd.finish(Message([image]))


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
    target = await _group_subscription_target(bot, event)
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
    target = await _group_subscription_target(bot, event)
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
    target = await _group_subscription_target(bot, event)
    if target is None:
        return
    enabled = toggle_hltv_event_prediction(target["id"])
    state_text = "已打开" if enabled else "已关闭"
    await cs_cmd.finish(f"{state_text}本群赛事竞猜功能")


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
        "完美平台 Session 已保存，现可使用 CS 战绩 pw 或 CS bind pw <昵称>。"
    )


async def _handle_cs_bind(
    event: MessageEvent,
    platform: str,
    nickname: str,
) -> None:
    """保存当前 QQ 指定平台的查询绑定。"""
    raw_nickname = nickname.strip()
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


@cs_cmd.assign("subcommands.bind")
async def handle_cs_bind(event: MessageEvent, params: Match[str]) -> None:
    """解析平台和昵称后执行绑定。"""
    raw_params = params.result.strip() if params.available else ""
    bind_args = raw_params.split(maxsplit=1)
    if len(bind_args) != 2:
        await cs_cmd.finish(CS_BIND_USAGE)
        return

    platform = normalize_platform(bind_args[0])
    if platform is None:
        await cs_cmd.finish(CS_BIND_USAGE)
        return
    await _handle_cs_bind(event, platform, bind_args[1])


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


@cs_cmd.assign("subcommands.check")
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
        await cs_cmd.finish(f"HLTV比赛信息查询失败，请之后重试：{exc}")
        return
    except Exception:
        logger.exception("CS 比赛 Rating 查询失败：%s", raw_url)
        await cs_cmd.finish("HLTV比赛信息查询失败或图片渲染失败，请稍后重试。")
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


@cs_cmd.assign("subcommands.sub")
async def handle_cs_sub(event: MessageEvent, event_id: Match[str]) -> None:
    raw_id = event_id.result.strip() if event_id.available else ""
    if not raw_id.isdigit():
        await cs_cmd.finish("赛事 ID 无效，请使用数字，例如：CS sub 8057")

    target = target_from_event(event)
    if target is None:
        await cs_cmd.finish("无法识别当前会话，暂时不能建立赛事订阅。")

    # 赛事订阅以 ID 为唯一键；当前会话重复订阅时只需追加推送目标，
    # 直接复用本地快照，避免再次访问 HLTV/FlareSolverr。
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

        if stored_entry.get("completed", False) or str(
            stored_entry.get("status", "")
        ) == EVENT_STATUS_FINISHED:
            await cs_cmd.finish(f"赛事{stored_name}已结束，无法再订阅")
            return

        if added:
            await cs_cmd.finish(
                f"已订阅此赛事：{stored_name}，已为当前会话加入推送。"
            )
            return
        await cs_cmd.finish(
            f"赛事{stored_name}已订阅此赛事，当前会话已在推送列表中。"
        )
        return

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
    event_settings = get_hltv_event_settings(target["id"])
    push_mode = (
        "每张地图开始、结束时推送；最后一张图结束时合并完整 Rating 汇总"
        if event_settings["push_each_map"]
        else "按系列赛级别推送开始和结束，整场结束时补发完整 Rating 汇总"
    )
    prediction_text = (
        "已打开本群赛事竞猜"
        if event_settings["prediction_enabled"]
        else "本群赛事竞猜未打开"
    )
    await cs_cmd.finish(
        f"{prefix} {event_data.name}，赛程时间为{_event_schedule_text(event_data)}\n"
        f"已记录 {len(refs)} 场比赛，轮询间隔为{config.hltv_poll_interval}秒；"
        f"{push_mode}；{prediction_text}。"
    )


@cs_cmd.assign("subcommands.unsub")
async def handle_cs_unsub(
    bot: Bot,
    event: MessageEvent,
    event_id: Match[str],
) -> None:
    """让当前群退订指定赛事，但保留其他目标的订阅。"""
    target = await _group_subscription_target(bot, event)
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
    )


@cs_cmd.assign("subcommands.prediction")
async def handle_cs_prediction(
    event: MessageEvent,
    params: Match[str],
) -> None:
    """解析竞猜和排行榜参数。"""
    if not isinstance(event, GroupMessageEvent):
        await cs_cmd.finish("竞猜功能仅支持群聊。")
        return

    raw_params = params.result.strip() if params.available else ""
    prediction_args = raw_params.split()
    if prediction_args and prediction_args[0].casefold() in {
        "rank",
        "排名",
    }:
        if len(prediction_args) != 2:
            await cs_cmd.finish("用法：CS prediction rank <本群|全部>")
            return
        scope_value = prediction_args[1].casefold()
        if scope_value in {"本群", "group"}:
            scope = "group"
            scope_label = "本群"
        elif scope_value in {"全部", "all"}:
            scope = "all"
            scope_label = "全部赛事"
        else:
            await cs_cmd.finish("用法：CS prediction rank <本群|全部>")
            return
        try:
            entries = await get_prediction_ranking(scope, str(event.group_id))
            image = await render_prediction_rank_card(
                entries,
                scope_label=scope_label,
            )
        except Exception:
            logger.exception("CS 竞猜排行榜渲染失败：scope=%s", scope)
            await cs_cmd.finish("竞猜排行榜处理失败，请稍后重试。")
            return
        await cs_cmd.finish(Message([image]))
        return

    if len(prediction_args) < 2:
        await cs_cmd.finish(CS_PREDICTION_USAGE)
        return
    if prediction_args[0].isdigit():
        points_text = prediction_args[0]
        team_name = " ".join(prediction_args[1:])
    elif prediction_args[-1].isdigit():
        points_text = prediction_args[-1]
        team_name = " ".join(prediction_args[:-1])
    else:
        await cs_cmd.finish(CS_PREDICTION_USAGE)
        return

    settings = get_hltv_event_settings(str(event.group_id))
    if not settings["prediction_enabled"]:
        await cs_cmd.finish("本群尚未打开赛事竞猜功能，请先使用 CS event predict。")
        return
    try:
        result = await place_prediction(
            str(event.group_id),
            str(event.user_id),
            team_name,
            int(points_text),
        )
    except PredictionError as exc:
        await cs_cmd.finish(str(exc))
        return
    except Exception:
        logger.exception(
            "CS 竞猜记录失败：group_id=%s user_id=%s",
            event.group_id,
            event.user_id,
        )
        await cs_cmd.finish("竞猜记录失败，请稍后重试。")
        return
    await cs_cmd.finish(
        f"已使用{result['points']}积分预测{result['team_name']}获胜。"
        f"（比赛编号：{result['match_id']}）"
    )


@cs_cmd.assign("subcommands.nosub")
async def handle_cs_nosub(bot: Bot, event: MessageEvent) -> None:
    """让当前群退订全部赛事推送。"""
    target = await _group_subscription_target(bot, event)
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
    await cs_cmd.finish(f"本群已退订全部赛事推送，共移除 {removed} 项订阅。")


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
    )


@scheduler.scheduled_job(
    "interval",
    seconds=config.hltv_poll_interval,
    id="madokabot_cs_match_subscribe_poll",
    max_instances=1,
    coalesce=True,
    # 机器人重启后立即检查持久化状态，避免错过赛事开始后的第一次轮询。
    next_run_time=datetime.now(timezone.utc),
)
async def _poll_cs_match_subscriptions() -> None:
    from .service import poll_subscriptions

    await poll_subscriptions()


@scheduler.scheduled_job(
    "interval",
    minutes=5,
    id="madokabot_cs_prediction_refund_expired",
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.now(timezone.utc),
)
async def _refund_expired_cs_predictions() -> None:
    """独立于网络抓取和订阅列表的竞猜退款兜底，只记录日志。"""
    from .prediction import refund_expired_predictions

    try:
        await refund_expired_predictions()
    except Exception:
        logger.exception("CS 超时竞猜退款失败，将在下一轮重试")
