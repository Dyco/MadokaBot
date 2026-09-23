from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class CopyingConfig(BaseModel):
    """复读机默认配置。"""

    copying_number: int = Field(
        default=3,
        ge=1,
        description="连续多少条相同消息时触发复读",
    )


config = get_plugin_config(CopyingConfig)
