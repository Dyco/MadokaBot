import json
from typing import Any

from nonebot import get_plugin_config
from pydantic import BaseModel, field_validator


class ChatConfig(BaseModel):
    model_api_key: str = "" # NVIDIA API 密钥
    model_base_url: str = "https://integrate.api.nvidia.com/v1" # OpenAI 兼容 API 地址
    set_model: list[str] = ["meta/llama-3.1-70b-instruct"] # 聊天模型列表
    chat_timeout: float = 60.0 # 请求超时时间，单位秒
    chat_max_tokens: int = 2048 # 单次聊天最大输出 token 数

    @field_validator("set_model", mode="before")
    @classmethod
    def normalize_models(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
                raise ValueError("set_model 的 JSON 配置必须是模型名称列表")
            return [item.strip() for item in stripped.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError("set_model 必须是列表、JSON 列表或逗号分隔字符串")


config = get_plugin_config(ChatConfig)
