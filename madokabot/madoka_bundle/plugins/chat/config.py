import json
from typing import Any

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class ChatConfig(BaseModel):
    model_api_key: str = Field(default="", description="NVIDIA API Key")
    model_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="OpenAI-compatible API base URL",
    )
    set_model: list[str] = Field(
        default_factory=lambda: ["meta/llama-3.1-70b-instruct"],
        description="Ordered fallback model list for the chat plugin",
    )
    chat_timeout: float = Field(default=60.0, description="Request timeout in seconds")
    chat_max_tokens: int = Field(
        default=2048,
        description="Maximum output tokens for each chat request",
    )

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
