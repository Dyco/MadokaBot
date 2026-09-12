from arclet.alconna import StrMulti
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot_plugin_alconna import (
    Alconna,
    Arparma,
    Args,
    MsgTarget,
    Subcommand,
    on_alconna,
)

from ...madoka_bundle.plugins.common import is_group_whitelisted


RSS_USAGE = """用法：
RSS 添加 <名称> <RSS 地址>
RSS rsshub_add <路由名>
RSS 删除 <名称 ...>
RSS 查看 [名称]
RSS 查看全部 [关键词]
RSS 修改 <名称 ...> 属性=值
RSS cookies <名称> <cookies>
RSS 上传文件 <磁力或 torrent 地址>
RSS 选择文件 <GID> <编号，如 1,3-5>
RSS 终止 <GID>

也可以使用“订阅”作为 RSS 的别名。"""

RSS_MANAGE_PERMISSION = GROUP_ADMIN | GROUP_OWNER | SUPERUSER
RSS_GROUP_WHITELIST_MESSAGE = "本群未加入 RSS 白名单，无法使用 RSS 功能。"


rss_cmd_alc = Alconna(
    "RSS",
    Subcommand(
        "add",
        Args["content?", StrMulti],
        alias=["添加", "添加订阅", "sub"],
        help_text="添加 RSS 订阅",
    ),
    Subcommand(
        "rsshub_add",
        Args["content?", StrMulti],
        alias=["rsshub-add", "RSSHub添加"],
        help_text="通过 RSSHub 路由添加订阅",
    ),
    Subcommand(
        "deldy",
        Args["content?", StrMulti],
        alias=["删除", "删除订阅", "drop", "unsub"],
        help_text="取消或删除订阅",
    ),
    Subcommand(
        "show",
        Args["content?", StrMulti],
        alias=["查看", "查看订阅"],
        help_text="查看订阅详情",
    ),
    Subcommand(
        "show_all",
        Args["content?", StrMulti],
        alias=["查看全部", "所有订阅", "showall", "select_all", "selectall"],
        help_text="查看订阅列表",
    ),
    Subcommand(
        "change",
        Args["content?", StrMulti],
        alias=["修改", "修改订阅", "modify"],
        help_text="修改订阅设置",
    ),
    Subcommand(
        "add_cookies",
        Args["content?", StrMulti],
        alias=["cookies", "添加cookies"],
        help_text="设置订阅 cookies",
    ),
    Subcommand(
        "upload_file",
        Args["content?", StrMulti],
        alias=["上传文件", "uploadfile"],
        help_text="下载并上传文件到群文件",
    ),
    Subcommand(
        "close",
        Args["content?", StrMulti],
        alias=["终止", "终止下载", "cancel"],
        help_text="终止 aria2 下载任务",
    ),
    Subcommand(
        "select_file",
        Args["content?", StrMulti],
        alias=["选择文件", "选择下载", "select"],
        help_text="选择多文件种子中要下载的文件",
    ),
)


rss_cmd = on_alconna(
    rss_cmd_alc,
    aliases={"订阅"},
    priority=5,
    block=False,
)


async def check_rss_manage_permission(
    event: Event, bot: Bot, _: T_State, __: Arparma
) -> bool:
    """为管理类子命令复用原有的 NoneBot 权限规则。"""

    if not isinstance(event, GroupMessageEvent):
        return False
    if not is_group_whitelisted(event.group_id):
        await bot.send(event, RSS_GROUP_WHITELIST_MESSAGE)
        return False
    return await RSS_MANAGE_PERMISSION(bot, event)


async def check_group_message(
    event: Event, bot: Bot, __: T_State, ___: Arparma
) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if not is_group_whitelisted(event.group_id):
        await bot.send(event, RSS_GROUP_WHITELIST_MESSAGE)
        return False
    return True


# 先由主 matcher 确认子命令，再进入各自独立的处理链。
# 这样 got() 只会在对应子命令中启动，不会抢占其他命令的消息。
rss_add_cmd = rss_cmd.dispatch(
    "add", additional=check_rss_manage_permission, block=True
)
rsshub_cmd = rss_cmd.dispatch(
    "rsshub_add", additional=check_rss_manage_permission, block=True
)
rss_remove_cmd = rss_cmd.dispatch(
    "deldy", additional=check_rss_manage_permission, block=True
)
rss_show_cmd = rss_cmd.dispatch(
    "show", additional=check_rss_manage_permission, block=True
)
rss_show_all_cmd = rss_cmd.dispatch(
    "show_all", additional=check_rss_manage_permission, block=True
)
rss_edit_cmd = rss_cmd.dispatch(
    "change", additional=check_rss_manage_permission, block=True
)
rss_cookies_cmd = rss_cmd.dispatch(
    "add_cookies", additional=check_rss_manage_permission, block=True
)
rss_upload_cmd = rss_cmd.dispatch(
    "upload_file", additional=check_group_message, block=True
)
rss_close_cmd = rss_cmd.dispatch(
    "close", additional=check_rss_manage_permission, block=True
)
rss_select_file_cmd = rss_cmd.dispatch(
    "select_file", additional=check_group_message, block=True
)


@rss_cmd.handle()
async def handle_rss_root(
    event: Event, target: MsgTarget, result: Arparma
) -> None:
    if target.private:
        await rss_cmd.finish("暂不支持私聊消息")
    if not result.subcommands:
        if isinstance(event, GroupMessageEvent) and not is_group_whitelisted(
            event.group_id
        ):
            await rss_cmd.finish(RSS_GROUP_WHITELIST_MESSAGE)
        await rss_cmd.finish(RSS_USAGE)
