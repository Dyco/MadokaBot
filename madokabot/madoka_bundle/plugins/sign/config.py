from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class SignConfig(BaseModel):
    sign_keywords: list[str] = Field(default_factory=lambda: ["打卡", "签到"])


config = get_plugin_config(SignConfig)
