"""账号注册、资料查询、改名与立绘设置。"""

from nonebot.plugin import PluginMetadata

from .config import AccountConfig

__plugin_meta__ = PluginMetadata(
    name="账号",
    description="注册账号、查询用户资料、付费改名和设置已拥有的立绘",
    usage="注册\n设置 立绘 <立绘ID>\n设置 改名 <名字>（最多 10 字，消耗 10 积分）\n查询 立绘/资料",
    type="application",
    config=AccountConfig,
)

from . import registration as registration  # noqa: E402,F401
from . import profile as profile  # noqa: E402,F401
