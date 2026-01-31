from pydantic import BaseModel
from nonebot import get_plugin_config
from typing import List

class SignConfig(BaseModel):
    sign_keywords: List[str] = ["打卡", "签到"]

# 实例化配置
config = get_plugin_config(SignConfig)