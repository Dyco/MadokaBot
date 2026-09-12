from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

SET_USAGE = "set chara <立绘ID>"
QUERY_USAGE = "query chara\nquery data"
SHOP_USAGE = "shop chara\nshop list\nshop buy <编号>"

set_cmd_alc = Alconna(
    "set",
    Subcommand("chara", Args["id?", str], alias=["立绘"]),
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
