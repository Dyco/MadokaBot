from nonebot.plugin import PluginMetadata

from .config import CommonConfig

__plugin_meta__ = PluginMetadata(
    name="通用插件",
    description="通用指令集合，包含设置、查询和商店功能",
    usage=(
        "请使用以下指令：\n"
        "注册\n"
        "set chara <立绘ID>\n"
        "query chara\n"
        "query data\n"
        "shop help\n"
        "shop chara\n"
        "shop list\n"
        "shop buy <编号>\n"
        "群白名单 添加 [群号]\n"
        "群白名单 删除 [群号]\n"
        "群白名单 列表 [页码]"
    ),
    type="application",
    config=CommonConfig,
)

# Import matcher definitions before attaching command handlers.
from . import matchers as matchers  # noqa: E402
from . import group_whitelist as group_whitelist  # noqa: E402
from .group_whitelist import is_group_whitelisted  # noqa: E402,F401
from .media import (  # noqa: E402,F401
    LocalMedia,
    MediaDelivery,
    MediaDeliveryMode,
    MediaDeliveryResult,
    media_delivery,
)
from . import registration as registration  # noqa: E402
from . import profile as profile  # noqa: E402
from . import shop as shop  # noqa: E402
