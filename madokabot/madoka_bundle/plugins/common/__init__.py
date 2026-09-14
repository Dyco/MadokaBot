from nonebot.plugin import PluginMetadata

from .config import CommonConfig

__plugin_meta__ = PluginMetadata(
    name="通用插件",
    description="通用指令集合，包含设置、查询和商店功能",
    usage=(
        "请使用以下指令：\n"
        "注册\n"
        "设置 立绘 <立绘ID>\n"
        "查询 立绘/数据\n"
        "商店 立绘/列表/购买 <编号>\n"
        "群白名单 添加/删除/列表 <群号>\n"
    ),
    type="application",
    config=CommonConfig,
)

# Import matcher definitions before attaching command handlers.
from . import matchers as matchers  # noqa: E402
from . import group_whitelist as group_whitelist  # noqa: E402
from .group_whitelist import is_group_whitelisted  # noqa: E402,F401
from .file_cleanup import (  # noqa: E402,F401
    cleanup_expired_files,
    register_cleanup_path,
)
from .media import (  # noqa: E402,F401
    LocalMedia,
    MediaDelivery,
    MediaDeliveryMode,
    MediaDeliveryResult,
    MediaSizeLimitExceeded,
    media_delivery,
)
from . import registration as registration  # noqa: E402
from . import profile as profile  # noqa: E402
from . import shop as shop  # noqa: E402
