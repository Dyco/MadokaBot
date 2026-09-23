"""业务命令定义。"""

from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

WHITELIST_USAGE = "群白名单 添加 [群号]\n群白名单 删除 [群号]\n群白名单 列表"

BLACKLIST_USAGE = "群黑名单 添加 [群号]\n群黑名单 删除 [群号]\n群黑名单 列表"

group_whitelist_cmd_alc = Alconna(
    "groupWhitelist",
    Subcommand("add", Args["group_id?", str], alias=["添加", "新增"]),
    Subcommand("delete", Args["group_id?", str], alias=["删除", "移除"]),
    Subcommand("list", alias=["列表"]),
)

group_blacklist_cmd_alc = Alconna(
    "groupBlacklist",
    Subcommand("add", Args["group_id?", str], alias=["添加", "新增"]),
    Subcommand("delete", Args["group_id?", str], alias=["删除", "移除"]),
    Subcommand("list", alias=["列表"]),
)

group_whitelist_cmd = on_alconna(
    group_whitelist_cmd_alc,
    use_cmd_start=True,
    aliases={"群白名单"},
    priority=10,
    block=True,
)

group_blacklist_cmd = on_alconna(
    group_blacklist_cmd_alc,
    use_cmd_start=True,
    aliases={"群黑名单"},
    priority=10,
    block=True,
)
