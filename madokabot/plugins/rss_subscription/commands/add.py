import re

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText
from nonebot_plugin_alconna import Match as AlcMatch

from .. import scheduler
from ..subscription import Rss
from .matchers import rss_add_cmd


@rss_add_cmd.handle()
async def prepare_rss_add(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and re.match(r"^\S+\s+\S+$", content.result.strip()):
        matcher.set_arg("RSS_ADD", Message(content.result))


prompt = """\
通过 RSS 添加 <名称> <RSS 地址> 命令添加订阅
空格分割
默认订阅到当前群组
更多信息可通过 RSS 修改 命令修改订阅设置\
"""


@rss_add_cmd.got("RSS_ADD", prompt=prompt)
async def handle_rss_add(
    matcher: Matcher,
    event: MessageEvent,
    name_and_url: str = ArgPlainText("RSS_ADD"),
) -> None:
    try:
        name, url = name_and_url.strip().split(maxsplit=1)
    except ValueError:
        await rss_add_cmd.reject(prompt)
        return
    if not name or not url:
        await rss_add_cmd.reject(prompt)
        return

    if Rss.get_one_by_name(name):
        await rss_add_cmd.finish(f"已存在订阅名为 {name} 的订阅")
        return

    await add_feed(name, url, event, matcher)


async def add_feed(
    name: str,
    url: str,
    event: MessageEvent,
    matcher: Matcher,
) -> None:
    if existing := Rss.get_one_by_url(url):
        current_group = (
            str(event.group_id) if isinstance(event, GroupMessageEvent) else None
        )
        if current_group and current_group in existing.group_id:
            await matcher.finish(
                f"当前群已经订阅该地址，订阅名为：{existing.name}"
            )
        message = f"该地址已经存在，订阅名为：{existing.name}"
        if current_group:
            message += f"\n请使用 /RSS 加入 {existing.name} 让当前群接收推送。"
        await matcher.finish(message)
        return

    rss = Rss()
    rss.name = name
    rss.url = url
    user = str(event.user_id) if isinstance(event, PrivateMessageEvent) else None
    group = str(event.group_id) if isinstance(event, GroupMessageEvent) else None
    guild_channel = None
    rss.add_user_or_group_or_channel(user, group, guild_channel)
    await matcher.send(f"👏 已成功添加订阅 {name} ！")
    await scheduler.add_job(rss)
