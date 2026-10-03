"""积分转账与排名等默认积分功能。"""

from nonebot.plugin import PluginMetadata

from .matchers import POINT_USAGE

__plugin_meta__ = PluginMetadata(
    name="积分",
    description="向已注册用户转账积分，查询本群与全部用户积分排名",
    usage=POINT_USAGE,
    type="application",
)

from . import handlers as handlers  # noqa: E402,F401
