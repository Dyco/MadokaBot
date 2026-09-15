"""CS/HLTV 指令注册。"""

from __future__ import annotations

from arclet.alconna import StrMulti
from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
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
from .player_stats import (
    PlayerStatsError,
    bind_player,
    fetch_player_stats,
    get_binding,
    platform_label,
)
from .render import render_event_list_card, render_player_stats_card
from .service import render_check_rating_messages, send_rating_forward
from .storage import subscribe_event, target_from_event

BOT_NAME = "圆香"
UNSUPPORTED_LINK_MESSAGE = f"{BOT_NAME}暂不支持此链接"

CS_USAGE = """用法：
CS help
CS list event  列出当前及未来三个月的高奖金国际 LAN 和 Major 赛事
CS sub <赛事ID>  订阅赛事并推送其中的比赛结果
CS check <比赛链接>  查询一场比赛的 Rating
CS bind <5e|5E|pw|PW|完美> <昵称>  绑定平台战绩查询对象
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
        "bind",
        Subcommand(
            "5e",
            Args["nickname?", StrMulti],
            alias=["5E"],
            help_text="绑定 5E 玩家昵称",
        ),
        Subcommand(
            "pw",
            Args["nickname?", StrMulti],
            alias=["PW", "完美"],
            help_text="绑定完美平台玩家昵称",
        ),
        alias=["绑定"],
        help_text="绑定 5E 或完美平台玩家昵称",
    ),
    Subcommand(
        "5e",
        Args["nickname?", StrMulti],
        alias=["5E", "5e战绩", "5e查询"],
        help_text="查询 5E 玩家战绩",
    ),
    Subcommand(
        "pw",
        Args["nickname?", StrMulti],
        alias=["PW", "完美", "完美战绩", "pw查询"],
        help_text="查询完美平台玩家战绩",
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


async def _handle_cs_bind(
    event: MessageEvent,
    platform: str,
    nickname: Match[str],
) -> None:
    """保存当前 QQ 指定平台的查询绑定。"""
    raw_nickname = nickname.result.strip() if nickname.available else ""
    if not raw_nickname:
        await cs_cmd.finish(f"用法：CS bind {platform} <昵称>")

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
            "当前未配置完美平台登录态，查询前请准备 pw_session.json。"
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


async def _handle_cs_player_stats(
    event: MessageEvent,
    platform: str,
    nickname: Match[str],
) -> None:
    """读取绑定或昵称并渲染平台战绩卡片。"""
    raw_nickname = nickname.result.strip() if nickname.available else ""
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
    await _handle_cs_player_stats(event, "5e", nickname)


@cs_cmd.assign("pw")
async def handle_cs_pw(event: MessageEvent, nickname: Match[str]) -> None:
    """处理完美平台聚合战绩查询。"""
    await _handle_cs_player_stats(event, "pw", nickname)


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
        match = await fetch_match(match_id)
        messages = await render_check_rating_messages(match)
    except HltvError as exc:
        logger.warning("CS 比赛链接解析失败：%s (%s)", raw_url, exc)
        await cs_cmd.finish(UNSUPPORTED_LINK_MESSAGE)
        return
    except Exception:
        logger.exception("CS 比赛 Rating 查询失败：%s", raw_url)
        await cs_cmd.finish(UNSUPPORTED_LINK_MESSAGE)
        return

    if not messages:
        await cs_cmd.finish(UNSUPPORTED_LINK_MESSAGE)
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
        refs = await fetch_event_match_refs(raw_id)
        added = await subscribe_event(
            raw_id,
            target,
            event_name=event_data.name,
            event_url=event_data.url,
            event_end=event_data.end_at.isoformat() if event_data.end_at else "",
            match_refs=[
                {
                    "match_id": ref.match_id,
                    "section": ref.section,
                }
                for ref in refs
            ],
        )
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV 查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事订阅失败：%s", raw_id)
        await cs_cmd.finish("HLTV 赛事订阅处理失败，请稍后重试。")
        return

    prefix = "已订阅" if added else "已刷新订阅"
    await cs_cmd.finish(
        f"{prefix}：{event_data.name}（ID：{raw_id}）\n"
        f"已记录 {len(refs)} 场比赛，比赛开始、地图结束和系列赛结束后将使用合并转发推送。"
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
