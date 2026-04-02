from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class AskGeminiConfig(BaseModel):
    gemini_api_key: str = Field(default="", description="Gemini API Key")
    gemini_model: str = Field(default="gemini-1.5-flash", description="Gemini 模型名称")
    gemini_timeout: float = Field(default=60.0, description="Gemini 请求超时（秒）")


config = get_plugin_config(AskGeminiConfig)
