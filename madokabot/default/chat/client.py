"""聊天模型请求、响应解析与候选模型切换。"""

import re
import time
from typing import Any

import httpx
from nonebot import logger

from madokabot.core.config import config as madoka_config
from .config import config
from .prompts import get_system_prompt


def _build_endpoint(base_url: str) -> str:
    """将配置地址规范为聊天补全接口地址。"""
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _extract_text(content: Any) -> str:
    """提取字符串或分段响应中的文本内容。"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts).strip()
    return ""


def _strip_reasoning_markup(text: str) -> str:
    """移除模型响应中的思考标签及其内容。"""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


async def _request_with_model(
    client: httpx.AsyncClient,
    endpoint: str,
    api_key: str,
    model: str,
    question: str,
    mode: str,
) -> tuple[str, int | None]:
    """请求指定模型并解析回答和用量。"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": get_system_prompt(mode)},
            {"role": "user", "content": question},
        ],
        "max_tokens": config.chat_max_tokens,
        "temperature": 0.7,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = await client.post(endpoint, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("模型响应格式错误。")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("模型未返回可用内容。")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("模型响应格式错误。")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("模型响应中缺少消息内容。")
    answer = _extract_text(message.get("content"))
    answer = _strip_reasoning_markup(answer)
    if not answer:
        raise ValueError("模型返回为空。")

    usage = data.get("usage")
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    if not isinstance(total_tokens, int):
        total_tokens = None
    return answer, total_tokens


async def chat_completion(question: str, mode: str) -> tuple[str, int | None, float, str]:
    """依次尝试配置的模型，返回回答、用量、耗时和模型名。"""
    api_key = config.model_api_key.strip()
    if not api_key:
        raise ValueError("未配置 model_api_key，请先在环境中填写 API Key。")

    models = [model for model in config.set_model if model.strip()]
    if not models:
        raise ValueError("未配置 set_model，请先设置至少一个可用的模型名称。")

    endpoint = _build_endpoint(config.model_base_url.strip())
    start_time = time.perf_counter()
    errors: list[str] = []

    async with httpx.AsyncClient(
        proxy=madoka_config.proxy,
        timeout=config.chat_timeout,
    ) as client:
        for model in models:
            try:
                answer, total_tokens = await _request_with_model(
                    client=client,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model,
                    question=question,
                    mode=mode,
                )
                elapsed = time.perf_counter() - start_time
                return answer, total_tokens, elapsed, model
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(f"Model fallback failed for {model} ({mode}): {exc}")
                errors.append(f"{model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有模型都调用失败。\n" + "\n".join(errors[-5:]))
