"""积分查询、转账、赠礼、红包与排名功能。"""

from nonebot.plugin import PluginMetadata

from .matchers import POINT_USAGE

__plugin_meta__ = PluginMetadata(
    name="积分",
    description="查询积分与排名、转账和赠礼，发送群红包供群成员回复领取",
    usage=POINT_USAGE,
    type="application",
    extra={"help_category": "基础功能", "help_order": 20},
)

from . import handlers as handlers  # noqa: E402,F401
from . import red_packet as red_packet  # noqa: E402,F401
