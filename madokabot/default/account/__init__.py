"""账号注册、资料查询、改名与立绘设置。"""

from nonebot.plugin import PluginMetadata

from .config import AccountConfig

__plugin_meta__ = PluginMetadata(
    name="账号",
    description="注册账号、查询资料和库存、付费改名、切换立绘及签到模板",
    usage="注册\n设置 立绘 <立绘ID>\n设置 签到模板 <模板ID>\n设置 改名 <名字>（最多10字，消耗10积分）\n查询 立绘/签到模板/资料/积分",
    type="application",
    config=AccountConfig,
    extra={"help_category": "基础功能", "help_order": 40},
)

from . import registration as registration  # noqa: E402,F401
from . import profile as profile  # noqa: E402,F401
