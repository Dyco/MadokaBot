"""群管理交互与自动退群配置。"""

from nonebot import get_plugin_config
from pydantic import AliasChoices, BaseModel, Field


class GroupConfig(BaseModel):
    """群名单分页与自动退群规则。"""

    group_session_timeout: float = Field(
        default=60.0,
        validation_alias=AliasChoices("group_session_timeout", "shop_session_timeout"),
        description="群名单翻页超时秒数，兼容拆分前共用的商店超时配置",
    )
    auto_leave_group_min_members: int = 5  # 自动退群人数下限
    auto_leave_group_max_members: int = 200  # 自动退群人数上限


config = get_plugin_config(GroupConfig)
