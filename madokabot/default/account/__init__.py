"""账号注册、资料查询、改名与立绘设置。"""

from nonebot.plugin import PluginMetadata

from madokabot.core.config import command_start

from .config import AccountConfig

__plugin_meta__ = PluginMetadata(
    name="账号",
    description="注册账号、查询资料和库存、付费改名、切换立绘及签到模板",
    usage=f"注册/register（也支持/注册、/register）\n{command_start}设置 立绘 <立绘ID>\n{command_start}设置 签到模板 <模板ID>\n{command_start}设置 改名 <名字>（最多10字，消耗10积分）\n{command_start}查询 立绘/签到模板/资料/积分",
    type="application",
    config=AccountConfig,
    extra={"help_category": "基础功能", "help_order": 40},
)

from . import registration as registration  # noqa: E402,F401
from . import profile as profile  # noqa: E402,F401
