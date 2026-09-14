"""CS/HLTV 指令注册。"""

from __future__ import annotations

from arclet.alconna import StrMulti
from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot_plugin_alconna import (
    Alconna,
    Arparma,
    Args,
    Match,
    Subcommand,
    on_alconna,
)
from nonebot_plugin_apscheduler import scheduler

from .client import HltvError, fetch_match
from .config import config
from .service import _summary, render_and_subscribe_match
from .storage import subscribe, target_from_event


CS_USAGE = """用法：
CS help
CS sub <赛事ID>  订阅比赛并查询 Rating

示例：
CS sub 2397623

订阅后，比赛进行中的比分变化和结束后的 Rating 结果会推送到当前会话。"""


cs_command = Alconna(
    "cs",
    Subcommand("help", alias=["帮助"], help_text="查看 CS 赛事指令帮助"),
    Subcommand(
        "sub",
        Args["match_id", StrMulti],
        alias=["订阅"],
        help_text="订阅 HLTV 比赛并查询结果",
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


@cs_cmd.assign("sub")
async def handle_cs_sub(event: MessageEvent, match_id: Match[str]) -> None:
    raw_id = match_id.result.strip() if match_id.available else ""
    if not raw_id.isdigit():
        await cs_cmd.finish("赛事 ID 无效，请使用数字，例如：CS sub 2397623")

    target = target_from_event(event)
    if target is None:
        await cs_cmd.finish("无法识别当前会话，暂时不能建立赛事订阅。")

    await cs_cmd.send("正在获取 HLTV 赛事数据并缓存队标、选手图…")
    try:
        match = await fetch_match(raw_id)
        image = await render_and_subscribe_match(match)
        added = await subscribe(
            raw_id,
            target,
            fingerprint=match.fingerprint(),
            completed=match.is_finished and match.has_stats,
        )
    except HltvError as exc:
        await cs_cmd.finish(f"HLTV 查询失败：{exc}")
        return
    except Exception:
        logger.exception("CS 赛事查询失败：%s", raw_id)
        await cs_cmd.finish("HLTV 赛事数据处理失败，请稍后重试。")
        return

    prefix = "已订阅" if added else "已刷新订阅"
    if image is not None:
        await cs_cmd.finish(
            Message([MessageSegment.text(f"{prefix}：{match.display_title}\n"), image])
        )
    if match.is_finished:
        await cs_cmd.finish(f"{prefix}：{_summary(match)}")
    await cs_cmd.finish(
        f"{prefix}：{_summary(match)}\n比赛开始或状态变化后会推送更新。"
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
