"""业务命令定义。"""

from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

SHOP_USAGE = "商店 列表\n商店 立绘\n商店 签到模板\n商店 购买 <商品编号，如 skin01 / sign02>"

shop_cmd_alc = Alconna(
    "shop",
    Subcommand("help", alias=["帮助"]),
    Subcommand("chara", alias=["立绘", "skin", "皮肤", "角色立绘"]),
    Subcommand("sign", alias=["签到", "签到模板"]),
    Subcommand("list", alias=["列表"]),
    Subcommand("buy", Args["number?", str], alias=["购买"]),
)

shop_cmd = on_alconna(
    shop_cmd_alc,
    use_cmd_start=True,
    aliases={"商店"},
    priority=10,
    block=True,
)
