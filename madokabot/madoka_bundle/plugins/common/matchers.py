# -*- coding: utf-8 -*-

from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna
from nonebot import on_message
from nonebot.rule import fullmatch

SET_USAGE = "设置 立绘 <立绘编号>"
QUERY_USAGE = "查询 立绘\数据"
SHOP_USAGE = "商店 立绘\n列表\nshop购买 <编号>"
WHITELIST_USAGE = (
    "群白名单 添加 [群号]\n"
    "群白名单 删除 [群号]\n"
    "群白名单 列表"
)
BLACKLIST_USAGE = (
    "群黑名单 添加 [群号]\n"
    "群黑名单 删除 [群号]\n"
    "群黑名单 列表"
)
register_keywords : list[str] = ["注册", "register"]
help_keywords : list[str] = ["帮助", "help"]

register_cmd = on_message(rule=fullmatch(register_keywords))
help_cmd = on_message(rule=fullmatch(help_keywords))


set_cmd_alc = Alconna(
    "set",
    Subcommand("chara", Args["skin_id?", str], alias=["立绘"]),
)
query_cmd_alc = Alconna(
    "query",
    Subcommand("chara", alias=["立绘"]),
    Subcommand("data", alias=["资料"]),
)
shop_cmd_alc = Alconna(
    "shop",
    Subcommand("help", alias=["帮助"]),
    Subcommand("chara", alias=["立绘"]),
    Subcommand("list", alias=["列表"]),
    Subcommand("buy", Args["number?", str], alias=["购买"]),
)
group_whitelist_cmd_alc = Alconna(
    "groupWhitelist",
    Subcommand("add", Args["group_id?", str], alias=["添加","新增"]),
    Subcommand("delete", Args["group_id?", str], alias=["删除","移除"]),
    Subcommand("list", alias=["列表"]),
)
group_blacklist_cmd_alc = Alconna(
    "groupBlacklist",
    Subcommand("add", Args["group_id?", str], alias=["添加","新增"]),
    Subcommand("delete", Args["group_id?", str], alias=["删除","移除"]),
    Subcommand("list", alias=["列表"]),
)

set_cmd = on_alconna(
    set_cmd_alc,
    aliases={"设置"},
    priority=10,
    block=True,
)
query_cmd = on_alconna(
    query_cmd_alc,
    aliases={"查询"},
    priority=10,
    block=True,
)
shop_cmd = on_alconna(
    shop_cmd_alc,
    aliases={"商店"},
    priority=10,
    block=True,
)
group_whitelist_cmd = on_alconna(
    group_whitelist_cmd_alc,
    aliases={"群白名单"},
    priority=10,
    block=True,
)
group_blacklist_cmd = on_alconna(
    group_blacklist_cmd_alc,
    aliases={"群黑名单"},
    priority=10,
    block=True,
)

help_common_cmd = on_alconna(
    "help",
    aliases={"帮助"},
    priority=10,
    block=True,
)