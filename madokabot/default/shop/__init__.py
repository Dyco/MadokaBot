"""立绘、签到模板商店与购买指令。"""

from nonebot.plugin import PluginMetadata

from .config import ShopConfig

__plugin_meta__ = PluginMetadata(
    name="商店",
    description="浏览立绘和签到模板，使用积分购买并收入库存",
    usage="商店 列表\n商店 立绘\n商店 签到模板\n商店 购买 <skin01 / sign02>",
    type="application",
    config=ShopConfig,
)

from . import handlers as handlers  # noqa: E402,F401
