import asyncio
import re
from typing import List, Optional

from nonebot.adapters.onebot.v11 import ActionFailed, GroupMessageEvent, MessageEvent
from nonebot_plugin_alconna import Match as AlcMatch

from ..subscription import Rss
from .matchers import rss_show_all_cmd, rss_show_cmd


def handle_rss_list(rss_list: List[Rss]) -> str:
    rss_info_list = [
        f"（已停止）{i.name}：{i.url}" if i.stop else f"{i.name}：{i.url}"
        for i in rss_list
    ]
    return "\n\n".join(rss_info_list)


def show_rss_by_name(
    rss_name: str, group_id: Optional[int], guild_channel_id: Optional[str]
) -> str:
    rss = Rss.get_one_by_name(rss_name)
    if (
        rss is None
        or (group_id and str(group_id) not in rss.group_id)
        or (guild_channel_id and guild_channel_id not in rss.guild_channel_id)
    ):
        return f"❌ 订阅 {rss_name} 不存在或未订阅！"
    # 隐私考虑，不展示除当前群组或频道外的群组、频道和QQ
    return str(rss.hide_some_infos(group_id, guild_channel_id))


# 不带订阅名称默认展示当前群组或账号的订阅，带订阅名称就显示该订阅的
@rss_show_cmd.handle()
async def handle_rss_show(event: MessageEvent, content: AlcMatch[str]) -> None:
    rss_name = content.result.strip() if content.available else ""

    user_id = event.get_user_id()
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    guild_channel_id = None

    if rss_name:
        rss_msg = show_rss_by_name(rss_name, group_id, guild_channel_id)
        await rss_show_cmd.finish(rss_msg)

    if group_id:
        rss_list = Rss.get_by_group(group_id=group_id)
    elif guild_channel_id:
        rss_list = Rss.get_by_guild_channel(guild_channel_id=guild_channel_id)
    else:
        rss_list = Rss.get_by_user(user=user_id)

    if rss_list:
        msg_str = handle_rss_list(rss_list)
        await rss_show_cmd.finish(msg_str)
    else:
        await rss_show_cmd.finish("❌ 当前没有任何订阅！")


def filter_results_by_keyword(
    rss_list: List[Rss],
    search_keyword: str,
    group_id: Optional[int],
    guild_channel_id: Optional[str],
) -> List[Rss]:
    try:
        keyword = re.compile(search_keyword, flags=re.I)
    except re.error:
        return []
    return [
        rss
        for rss in rss_list
        if (
            keyword.search(rss.name)
            or keyword.search(rss.url)
            or (
                search_keyword.isdigit()
                and not group_id
                and not guild_channel_id
                and (
                    (rss.user_id and search_keyword in rss.user_id)
                    or (rss.group_id and search_keyword in rss.group_id)
                    or (
                        rss.guild_channel_id
                        and search_keyword in rss.guild_channel_id
                    )
                )
            )
        )
    ]


def get_rss_list(
    group_id: Optional[int], guild_channel_id: Optional[str]
) -> List[Rss]:
    if group_id:
        return Rss.get_by_group(group_id=group_id)
    if guild_channel_id:
        return Rss.get_by_guild_channel(guild_channel_id=guild_channel_id)
    return Rss.read_rss()


@rss_show_all_cmd.handle()
async def handle_rss_show_all(event: MessageEvent, content: AlcMatch[str]) -> None:
    search_keyword = content.result.strip() if content.available else ""
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    guild_channel_id = None

    rss_list = get_rss_list(group_id, guild_channel_id)
    if not rss_list:
        await rss_show_all_cmd.finish("❌ 当前没有任何订阅！")
        return

    results = (
        filter_results_by_keyword(
            rss_list, search_keyword, group_id, guild_channel_id
        )
        if search_keyword
        else rss_list
    )
    if not results:
        await rss_show_all_cmd.finish("❌ 当前没有任何订阅！")
        return

    await rss_show_all_cmd.send(f"当前共有 {len(results)} 条订阅")
    results.sort(key=lambda rss: rss.get_url())
    await asyncio.sleep(0.5)
    page_size = 30
    while results:
        current_page = results[:page_size]
        try:
            await rss_show_all_cmd.send(handle_rss_list(current_page))
        except ActionFailed:
            if page_size <= 5:
                await rss_show_all_cmd.finish("❌ 订阅列表过长，消息发送失败。")
            page_size -= 5
            continue
        results = results[page_size:]
