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
from .render import render_event_list_card
from .service import render_check_rating_messages, send_rating_forward
from .storage import subscribe_event, target_from_event

BOT_NAME = "圆香"
UNSUPPORTED_LINK_MESSAGE = f"{BOT_NAME}暂不支持此链接"

CS_USAGE = """用法：
CS help
CS list event  列出当前及未来三个月的高奖金国际 LAN 和 Major 赛事
CS sub <赛事ID>  订阅赛事并推送其中的比赛结果
CS check <比赛链接>  查询一场比赛的 Rating

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


@cs_cmd.assign("check")
async def handle_cs_check(
    bot: Bot,
    event: MessageEvent,
    match_url: Match[str],
) -> None:
    """解析比赛链接并发送单图或合并转发 Rating。"""
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
