# -*- coding: utf-8 -*-

from nonebot.plugin import PluginMetadata

from .config import CommonConfig
from .group_set import GroupSetStore, group_set  # noqa: F401
from .json_data import JsonDataStore  # noqa: F401
from .response import StatusResponse, respond, respond_with_status  # noqa: F401

__plugin_meta__ = PluginMetadata(
    name="通用插件",
    description="通用指令集合，包含签到、设置、查询和商店功能",
    usage=(
        "请使用以下指令：\n"
        "注册\n"
        "设置 立绘 <立绘ID>\n"
        "查询 立绘/数据\n"
        "商店 立绘/列表/购买 <编号>\n"
        "群白名单 添加/删除/列表 [群号]\n"
        "群黑名单 添加/删除/列表 [群号]\n"
        "复读 打开/关闭\n"
    ),
    type="application",
    config=CommonConfig,
)

# Import matcher definitions before attaching command handlers.
from . import matchers as matchers  # noqa: E402
from . import help as help  # noqa: E402
from . import group_list as group_list  # noqa: E402
from . import auto_leave_group as auto_leave_group  # noqa: E402
from .group_list import (  # noqa: E402,F401
    GroupAccessStore,
    GroupAccessType,
    group_access,
)
from .auto_leave_group import schedule_auto_leave_group  # noqa: E402,F401
from .group_list import (  # noqa: E402,F401
    is_group_blacklisted,
    is_group_whitelisted,
)
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
