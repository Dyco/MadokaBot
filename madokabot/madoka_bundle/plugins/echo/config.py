from pydantic import BaseModel
from nonebot import get_plugin_config
from typing import List

class EchoConfig(BaseModel):
    echo_reply: str = "我在"
    echo_keywords: List[str] = ["ping", "円香"]

# 实例化配置
config = get_plugin_config(EchoConfig)