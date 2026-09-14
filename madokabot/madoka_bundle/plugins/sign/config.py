from nonebot import get_plugin_config
from pydantic import BaseModel


class SignConfig(BaseModel):
    sign_keywords: list[str] = ["打卡", "签到"] # 打卡关键词


config = get_plugin_config(SignConfig)
