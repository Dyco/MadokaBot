"""立绘、签到模板商店与购买指令。"""

from nonebot.plugin import PluginMetadata

from .config import ShopConfig

__plugin_meta__ = PluginMetadata(
    name="商店",
    description="使用积分购买立绘和签到模板，购买后需发送/设置指令切换使用",
    usage=(
        "/商店 列表：查看商品分类\n"
        "/商店 立绘：查看立绘与商品编号\n"
        "/商店 签到模板：查看签到模板与商品编号\n"
        "/商店 购买 <商品编号>：消耗积分购买，例如/商店 购买 sign02\n"
        "/设置 立绘 skin01：切换已拥有的立绘\n"
        "/设置 签到模板 sign02：切换已拥有的签到模板\n"
        "/积分 赠礼 <@用户|QQ号> <商品编号>：使用自己的积分为对方购买"
    ),
    type="application",
    config=ShopConfig,
    extra={"help_category": "基础功能", "help_order": 30},
)

from . import handlers as handlers  # noqa: E402,F401
