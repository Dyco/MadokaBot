"""积分查询、转账与排名功能。"""

from nonebot.plugin import PluginMetadata

from .matchers import POINT_USAGE

__plugin_meta__ = PluginMetadata(
    name="积分",
    description="查询个人积分、向已注册用户转账，查询本群与全部用户积分排名",
    usage=POINT_USAGE,
    type="application",
)

from . import handlers as handlers  # noqa: E402,F401
