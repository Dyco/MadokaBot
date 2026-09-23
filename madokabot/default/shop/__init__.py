"""立绘商店与购买指令。"""

from nonebot.plugin import PluginMetadata

from .config import ShopConfig

__plugin_meta__ = PluginMetadata(
    name="商店",
    description="浏览立绘商品并使用积分购买",
    usage="商店 立绘\n商店 列表\n商店 购买 <编号>",
    type="application",
    config=ShopConfig,
)

from . import handlers as handlers  # noqa: E402,F401
