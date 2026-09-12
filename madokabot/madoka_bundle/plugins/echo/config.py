from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class EchoConfig(BaseModel):
    echo_reply: str = "我在"
    echo_keywords: list[str] = Field(default_factory=lambda: ["ping", "円香"])


config = get_plugin_config(EchoConfig)
