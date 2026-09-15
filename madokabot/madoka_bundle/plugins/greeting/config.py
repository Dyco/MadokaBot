from nonebot import get_plugin_config
from pydantic import BaseModel


class GreetingConfig(BaseModel):
    greeting_message: str = "制作人，Madoka现已开始事务所相关活动，请开始工作吧。"


config = get_plugin_config(GreetingConfig)
