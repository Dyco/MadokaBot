"""业务命令定义。"""

from nonebot_plugin_alconna import Alconna, Args, Subcommand, on_alconna

SHOP_USAGE = (
    "/商店 列表：查看商品分类\n"
    "/商店 立绘：查看立绘与商品编号\n"
    "/商店 签到模板：查看签到模板与商品编号\n"
    "/商店 购买 <商品编号>：消耗积分购买，例如/商店 购买 sign02\n"
    "/设置 立绘 skin01：切换已拥有的立绘\n"
    "/设置 签到模板 sign02：切换已拥有的签到模板\n"
    "/积分 赠礼 <@用户|QQ号> <商品编号>：使用自己的积分为对方购买"
)

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
