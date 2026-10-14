"""LXNS 开发者 API 的只读查分客户端。"""

from typing import Literal

import httpx

from .config import config
from .models import Best50, Player, Score

API_BASE = "https://maimai.lxns.net/api/v0"


class LxnsError(ValueError):
    """可直接展示给用户的查分错误。"""


def api_error(code: int) -> LxnsError:
    """将接口状态映射为不包含密钥的中文提示。"""
    messages = {
        400: "查分参数无效，请检查好友码、曲目 ID 与谱面类型。",
        401: "LXNS 开发者 Token 无效，请联系机器人管理员。",
        403: "玩家未开放第三方查询权限，请在 LXNS 隐私设置中开放玩家资料和成绩查询。",
        404: "未找到玩家或成绩，请确认 LXNS 已绑定 QQ／好友码并同步了成绩。",
        429: "LXNS 请求过于频繁，请稍后重试。",
    }
    return LxnsError(messages.get(code, "LXNS 服务暂时不可用，请稍后重试。"))


async def request_api(
    game: Literal["maimai", "chunithm"], path: str, params: dict | None = None
) -> dict:
    """按游戏使用共用开发者密钥请求接口并解包统一响应。"""
    token = config.rhythmgame_lxns_token.get_secret_value().strip()
    if not token:
        raise LxnsError("尚未配置 LXNS 开发者 Token：RHYTHMGAME_LXNS_TOKEN。")
    try:
        async with httpx.AsyncClient(timeout=config.rhythmgame_request_timeout) as client:
            response = await client.get(
                f"{API_BASE}/{game}/{path}", headers={"Authorization": token}, params=params
            )
    except httpx.RequestError as exc:
        raise LxnsError("连接 LXNS 超时或网络不可用，请稍后重试。") from exc
    if response.is_error:
        raise api_error(response.status_code)
    try:
        payload = response.json()
    except ValueError as exc:
        raise LxnsError("LXNS 返回了无效数据，请稍后重试。") from exc
    if not payload.get("success"):
        raise api_error(payload.get("code", 500))
    return payload["data"]


async def get_player(identifier: str, *, qq: bool = False) -> Player:
    """按好友码或查分器绑定的 QQ 号获取玩家资料。"""
    path = f"player/qq/{identifier}" if qq else f"player/{identifier}"
    return Player.model_validate(await request_api("maimai", path))


async def get_b50(friend_code: int) -> Best50:
    """读取 LXNS 缓存的 Best 50，不自行重算版本分组。"""
    return Best50.model_validate(await request_api("maimai", f"player/{friend_code}/bests"))


async def get_score(
    friend_code: int, song_id: int, level_index: int, song_type: str
) -> Score:
    """查询指定曲目、难度和谱面类型的最佳成绩。"""
    data = await request_api(
        "maimai",
        f"player/{friend_code}/best",
        {"song_id": song_id, "level_index": level_index, "song_type": song_type},
    )
    return Score.model_validate(data)
