from nonebot import get_plugin_config
from pydantic import BaseModel


class EchoConfig(BaseModel):
    echo_reply: str = "我在" # 回复内容
    echo_keywords: list[str] = ["ping", "円香"] # 触发关键词


config = get_plugin_config(EchoConfig)
