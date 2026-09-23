"""5E 玩家搜索、身份解析和战绩查询。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx

from .constants import (
    FIVE_E_ID_URL,
    FIVE_E_MATCH_LIST_URL,
    FIVE_E_PLAYER_HOME_URL,
    FIVE_E_RETRY_ATTEMPTS,
    FIVE_E_RETRY_DELAY,
    FIVE_E_SEARCH_URL,
    RECENT_MATCH_LIMIT,
)
from .http import create_client, request_json
from .models import PlayerBinding, PlayerStatsError
from .values import as_dict, as_list, image_url
from .views.five_e import build_five_e_view


async def _search_5e_player(
    client: httpx.AsyncClient,
    nickname: str,
) -> dict[str, str]:
    """通过 5E 搜索接口选择精确昵称，否则选择首个结果。"""
    payload = await request_json(
        client,
        "GET",
        FIVE_E_SEARCH_URL,
        retry_attempts=FIVE_E_RETRY_ATTEMPTS,
        retry_delay=FIVE_E_RETRY_DELAY,
        params={"keywords": nickname},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": (
                f"https://arena.5eplay.com/search?keywords={quote(nickname, safe='')}"
            ),
        },
    )
    user_data = as_dict(as_dict(payload.get("data")).get("user"))
    candidates = []
    for item in as_list(user_data.get("list")):
        user = as_dict(item)
        name = str(user.get("username") or "").strip()
        domain = str(user.get("domain") or "").strip()
        if name and domain:
            candidates.append(
                {
                    "name": name,
                    "domain": domain,
                    "avatar": image_url(
                        user.get("avatar_url"),
                        base_url="https://oss-arena.5eplay.com",
                    ),
                }
            )
    if not candidates:
        raise PlayerStatsError(f"未找到 5E 玩家：{nickname}")
    nickname_key = nickname.casefold()
    return next(
        (item for item in candidates if item["name"].casefold() == nickname_key),
        candidates[0],
    )


async def resolve_five_e_uuid(
    client: httpx.AsyncClient,
    domain: str,
) -> str:
    """将 5E 玩家域名转换为战绩接口所需的 UUID。"""
    payload = await request_json(
        client,
        "POST",
        FIVE_E_ID_URL,
        retry_attempts=FIVE_E_RETRY_ATTEMPTS,
        retry_delay=FIVE_E_RETRY_DELAY,
        json={"trans": {"domain": domain}},
    )
    uuid = str(as_dict(payload.get("data")).get("uuid") or "").strip()
    if not uuid:
        raise PlayerStatsError("5E 玩家 UUID 获取失败")
    return uuid


async def resolve_five_e_identity(nickname: str) -> PlayerBinding:
    """根据 5E 昵称解析可查询的玩家绑定。"""
    async with create_client() as client:
        result = await _search_5e_player(client, nickname)
        uuid = await resolve_five_e_uuid(client, result["domain"])
    return PlayerBinding(
        user_id="",
        platform="5e",
        player_name=result["name"],
        domain=result["domain"],
        uuid=uuid,
        avatar_url=result["avatar"],
    )


def _extract_5e_match_list(payload: dict[str, Any]) -> list[Any]:
    """解析 5E match/list 返回的比赛数组。"""
    data = payload.get("data")
    if isinstance(data, list):
        return data
    raise PlayerStatsError("5E 近期比赛返回了未识别的数据结构")


async def _fetch_5e_recent_matches(
    client: httpx.AsyncClient,
    uuid: str,
) -> list[dict[str, Any]]:
    """读取 5E 最近十场；仅使用支持 limit 的 match/list 接口。"""
    payload = await request_json(
        client,
        "GET",
        FIVE_E_MATCH_LIST_URL,
        retry_attempts=FIVE_E_RETRY_ATTEMPTS,
        retry_delay=FIVE_E_RETRY_DELAY,
        params={
            "match_type": -1,
            "page": 1,
            "date": 0,
            "start_time": 0,
            "end_time": int(time.time()),
            "uuid": uuid,
            "limit": RECENT_MATCH_LIMIT,
            "cs_type": 0,
        },
    )
    matches = _extract_5e_match_list(payload)
    return [
        dict(item) for item in matches[:RECENT_MATCH_LIMIT] if isinstance(item, dict)
    ]


async def fetch_five_e_stats(binding: PlayerBinding) -> dict[str, Any]:
    """从 player_home 获取赛季/生涯资料，并单独读取近期逐场记录。"""
    async with create_client() as client:
        home_result = await request_json(
            client,
            "GET",
            FIVE_E_PLAYER_HOME_URL,
            retry_attempts=FIVE_E_RETRY_ATTEMPTS,
            retry_delay=FIVE_E_RETRY_DELAY,
            params={"uuid": binding.uuid},
        )
        home_data = as_dict(home_result.get("data"))
        expected_sections = ("career", "season_data", "uinfo", "elo_info")
        if not home_data or any(
            key not in home_data or not isinstance(home_data[key], dict)
            for key in expected_sections
        ):
            raise PlayerStatsError("5E player_home 返回了未识别的数据结构")

        # 两个阶段按顺序执行；比赛列表连续失败时也中断本次查询，
        # 避免返回缺少近期对局的半成品卡片。
        match_data = await _fetch_5e_recent_matches(client, binding.uuid)

    return build_five_e_view(binding, home_data, match_data)
