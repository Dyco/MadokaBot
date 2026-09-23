"""完美平台登录、玩家搜索和战绩查询。"""

from __future__ import annotations

from typing import Any

from nonebot.log import logger

from ..config import config
from .constants import (
    PW_CURRENT_SEARCH_URL,
    PW_LOGIN_URL,
    PW_MATCHES_URL,
    PW_PUBLIC_APPVERSION,
    PW_PUBLIC_DEVICE,
    PW_PUBLIC_TOKEN,
    PW_STATS_URL,
)
from .http import create_client, request_json
from .models import PlayerBinding, PlayerStatsError
from .session import load_pw_session, save_pw_session
from .values import as_dict, as_list, first_value, image_url, parse_steam_id
from .views.perfect_world import aggregate_pw_match_stats, build_pw_view


def _pw_headers(session: dict[str, Any]) -> dict[str, str]:
    """生成完美平台接口请求头。"""
    return {
        "appversion": str(session["appversion"]),
        "token": str(session["token"]),
        "platform": "android",
        "Content-Type": "application/json",
    }


def _pw_public_headers() -> dict[str, str]:
    """生成当前完美客户端公开数据接口所需的请求头。"""
    token = str(config.cs_pw_api_token or PW_PUBLIC_TOKEN).strip()
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "okhttp/4.11.0",
        "appversion": str(config.cs_pw_api_version or PW_PUBLIC_APPVERSION).strip(),
        "device": str(config.cs_pw_api_device or PW_PUBLIC_DEVICE).strip(),
        "token": token,
    }


async def login_pw(mobile: str, code: str) -> dict[str, Any]:
    """使用完美平台手机号验证码登录并保存查询所需会话。"""
    mobile = mobile.strip()
    code = code.strip()
    if not mobile:
        raise PlayerStatsError("缺少手机号")
    if not code:
        raise PlayerStatsError("缺少短信验证码")

    async with create_client() as client:
        payload = await request_json(
            client,
            "POST",
            PW_LOGIN_URL,
            json={
                "appId": 2,
                "mobilePhone": mobile,
                "securityCode": code,
            },
        )

    if payload.get("code") not in (0, "0"):
        raise PlayerStatsError(
            str(payload.get("description") or payload.get("message") or "登录失败")
        )

    result = as_dict(payload.get("result"))
    login_result = as_dict(result.get("loginResult"))
    account_info = as_dict(login_result.get("accountInfo"))
    token = str(first_value(account_info, "token", "accessToken") or "").strip()
    steam_id = parse_steam_id(
        first_value(account_info, "steamId", "steam_id", "mySteamId")
    )
    if not token or not steam_id:
        raise PlayerStatsError("登录成功但返回的 Session 信息不完整")

    save_pw_session(token, steam_id)
    return account_info | {"token": token, "steamId": steam_id}


def _pw_identity_candidates(payload: dict[str, Any]) -> list[PlayerBinding]:
    """解析当前完美平台搜索接口返回的玩家列表。"""
    result = payload.get("result")
    if not isinstance(result, list):
        raise PlayerStatsError("完美平台搜索返回了未识别的数据结构")
    users: list[Any] = []
    for item in result:
        group = as_dict(item)
        nested = group.get("data")
        if not isinstance(nested, list):
            raise PlayerStatsError("完美平台搜索结果缺少 data 列表")
        users.extend(nested)

    candidates: list[PlayerBinding] = []
    for item in users:
        user = as_dict(item)
        name = str(user.get("name") or "").strip()
        steam_id = str(user.get("steamId64Str") or "").strip()
        if not name or not steam_id:
            continue
        candidates.append(
            PlayerBinding(
                user_id="",
                platform="pw",
                player_name=name,
                domain=str(user.get("wanmeiId") or "").strip(),
                uuid=steam_id,
                avatar_url=image_url(user.get("avatar")),
            )
        )
    return candidates


def _pick_pw_identity(candidates: list[PlayerBinding], nickname: str) -> PlayerBinding:
    """只选择昵称唯一且与搜索词完全相同的完美平台玩家。"""
    nickname_key = nickname.casefold()
    exact_matches = [
        item for item in candidates if item.player_name.casefold() == nickname_key
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise PlayerStatsError(f"完美平台存在多个同名玩家：{nickname}，请提供更准确的昵称")
    raise PlayerStatsError(
        f"完美平台搜索结果中没有与“{nickname}”完全一致的昵称，请核对平台昵称后重试"
    )


async def resolve_pw_identity(nickname: str) -> PlayerBinding:
    """根据完美平台昵称解析 SteamID；公开搜索不再依赖手机号登录态。"""
    async with create_client() as client:
        payload = await request_json(
            client,
            "POST",
            PW_CURRENT_SEARCH_URL,
            headers=_pw_public_headers(),
            json={
                "text": nickname,
                "searchType": "USER",
                "circleId": "0",
                "page": 1,
                "pageSize": 20,
                "gameTypeStr": "1,2",
                "platform": "android",
                "sortType": 1,
            },
        )
        if payload.get("code") not in (0, "0"):
            raise PlayerStatsError(
                str(
                    payload.get("description")
                    or payload.get("message")
                    or "完美平台搜索失败"
                )
            )
        candidates = _pw_identity_candidates(payload)
        if candidates:
            return _pick_pw_identity(candidates, nickname)
    raise PlayerStatsError(f"未找到完美玩家：{nickname}")


async def _fetch_pw_public_stats(
    binding: PlayerBinding, target_id: int
) -> dict[str, Any]:
    """通过当前公开客户端接口读取完美平台玩家数据。"""
    headers = _pw_public_headers()
    async with create_client() as client:
        stats_payload = await request_json(
            client,
            "POST",
            PW_STATS_URL,
            headers=headers,
            json={
                # 当前接口允许查询公开资料；传入登录 Session 中的 SteamID
                # 会触发 4013（无效的账号），必须使用公开客户端的 0。
                "mySteamId": 0,
                "toSteamId": target_id,
                "accessToken": "",
                "csgoSeasonId": "",
            },
        )
        stats_error: PlayerStatsError | None = None
        if stats_payload.get("statusCode") not in (None, 0, "0"):
            stats_error = PlayerStatsError(
                str(stats_payload.get("errorMessage") or "完美平台战绩查询失败")
            )
        stats = as_dict(stats_payload.get("data"))

        try:
            recent_payload = await request_json(
                client,
                "POST",
                PW_MATCHES_URL,
                headers=headers,
                json={
                    "csgoSeasonId": "recent",
                    "dataSource": 3,
                    "mySteamId": 0,
                    "page": 1,
                    "pageSize": 50,
                    "pvpType": -1,
                    "toSteamId": target_id,
                },
            )
            if recent_payload.get("statusCode") not in (None, 0, "0"):
                raise PlayerStatsError(
                    str(
                        recent_payload.get("errorMessage") or "完美平台近期比赛获取失败"
                    )
                )
            recent_matches = [
                item
                for item in as_list(
                    as_dict(recent_payload.get("data")).get("matchList")
                )
                if isinstance(item, dict)
            ]
        except PlayerStatsError as exc:
            if not stats:
                raise stats_error or exc
            logger.warning("完美平台近期比赛获取失败：%s", exc)
            recent_matches = []

    if not stats:
        if recent_matches:
            stats = aggregate_pw_match_stats(binding, recent_matches)
        else:
            raise stats_error or PlayerStatsError("未找到有效的完美平台战绩数据")

    binding.player_name = str(stats.get("name") or binding.player_name)
    binding.avatar_url = binding.avatar_url or image_url(stats.get("avatar"))
    return build_pw_view(binding, stats, recent_matches)


async def _fetch_pw_stats_legacy(
    binding: PlayerBinding, target_id: int
) -> dict[str, Any]:
    """兼容旧版手机号登录 Session 的完美平台查询。"""
    session = load_pw_session()
    if not session:
        raise PlayerStatsError(
            "完美平台公开查询失败，请稍后重试；如需使用旧版登录态，请先使用 CS login <手机号> <验证码>"
        )

    headers = _pw_headers(session)
    async with create_client() as client:
        payload = await request_json(
            client,
            "POST",
            PW_STATS_URL,
            headers=headers,
            json={
                "mySteamId": int(session["my_steam_id"]),
                "toSteamId": target_id,
                "accessToken": "",
                "csgoSeasonId": "",
            },
        )
        if payload.get("statusCode") not in (None, 0, "0"):
            raise PlayerStatsError(
                str(payload.get("errorMessage") or "完美平台战绩查询失败")
            )
        stats = as_dict(payload.get("data"))
        if not stats:
            raise PlayerStatsError("未找到有效的完美平台战绩数据")

        recent_matches: list[Any] = []
        try:
            recent_payload = await request_json(
                client,
                "POST",
                PW_MATCHES_URL,
                headers=headers,
                json={
                    "csgoSeasonId": "recent",
                    "dataSource": 3,
                    "mySteamId": int(session["my_steam_id"]),
                    "page": 1,
                    "pageSize": 10,
                    "pvpType": -1,
                    "toSteamId": target_id,
                },
            )
            recent_matches = as_list(
                as_dict(recent_payload.get("data")).get("matchList")
            )
        except PlayerStatsError as exc:
            logger.warning("完美平台旧版近期比赛获取失败：%s", exc)

    binding.player_name = str(stats.get("name") or binding.player_name)
    binding.avatar_url = binding.avatar_url or image_url(stats.get("avatar"))
    return build_pw_view(binding, stats, recent_matches)


async def fetch_pw_stats(binding: PlayerBinding) -> dict[str, Any]:
    """请求完美平台聚合战绩和近期比赛。"""
    target_id = parse_steam_id(binding.uuid)
    if not target_id:
        raise PlayerStatsError("完美玩家 SteamID 无效")

    try:
        return await _fetch_pw_public_stats(binding, target_id)
    except PlayerStatsError as exc:
        # 公开接口变更时保留旧 Session 作为兜底，但不会把公开玩家误报成
        # “无效账号”；只有两条接口链路都失败才将错误返回给调用方。
        if not load_pw_session():
            raise
        logger.warning("完美平台公开查询失败，尝试旧版 Session：%s", exc)
        try:
            return await _fetch_pw_stats_legacy(binding, target_id)
        except PlayerStatsError:
            raise exc
