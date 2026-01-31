import re
import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from nonebot.log import logger
from typing import List, Optional, Dict, Tuple, Any
from datetime import datetime, timezone
import time
import threading
import asyncio

from .models import PlayerSummaries, PlayerData
from .constants import *


STEAM_ID_OFFSET = 76561197960265728

# ----------------------------
# HTTP CLIENT（修复并发关闭）
# ----------------------------
_http_client: Optional[httpx.AsyncClient] = None
_http_client_lock = asyncio.Lock()
_http_client_created_at: float = 0
HTTP_CLIENT_MAX_AGE = 60 * 30

async def get_http_client(proxy: Optional[str]) -> httpx.AsyncClient:
    global _http_client, _http_client_created_at

    async with _http_client_lock:
        now = time.time()

        need_recreate = (
            _http_client is None
            or _http_client.is_closed
            or now - _http_client_created_at > HTTP_CLIENT_MAX_AGE
        )

        if need_recreate:
            if _http_client is not None:
                try:
                    await _http_client.aclose()
                except Exception:
                    pass

            _http_client = httpx.AsyncClient(
                proxy=proxy,
                timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0,pool=10.0),
                headers={"User-Agent": "MadokaBot/SteamInfo"},
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    keepalive_expiry=30.0,
                    max_keepalive_connections=0 
                )
            )
            _http_client_created_at = now
            logger.info("Steam HTTP client recreated")

        return _http_client

# ----------------------------
# CACHE（修复线程不安全）
# ----------------------------
STEAM_USER_CACHE_TTL = 30
STEAM_USER_CACHE_MAXSIZE = 5000

_steam_user_cache: Dict[str, Tuple[float, dict]] = {}
STEAM_USER_CACHE_LOCK = threading.Lock()


def _cache_get(key: str, ttl: int) -> Optional[dict]:
    with STEAM_USER_CACHE_LOCK:
        value = _steam_user_cache.get(key)
        if not value:
            return None
        ts, data = value
        if time.time() - ts > ttl:
            _steam_user_cache.pop(key, None)
            return None
        return data


def _cache_set(key: str, data: dict):
    with STEAM_USER_CACHE_LOCK:
        if len(_steam_user_cache) >= STEAM_USER_CACHE_MAXSIZE:
            oldest_key = min(_steam_user_cache.items(), key=lambda x: x[1][0])[0]
            _steam_user_cache.pop(oldest_key, None)
        _steam_user_cache[key] = (time.time(), data)


async def get_steam_users_info_cached(
    steam_ids: List[str],
    api_key: str,
    proxy: Optional[str],
    ttl: int,
) -> dict:
    steam_ids_sorted = sorted(steam_ids)
    cache_key = f"{api_key}:{','.join(steam_ids_sorted)}"

    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    data = await get_steam_users_info(
        steam_ids=steam_ids_sorted,
        api_key=api_key,
        proxy=proxy,
    )

    _cache_set(cache_key, data)
    return data


# ----------------------------
# SteamID 解析（修复返回类型）
# ----------------------------
def get_steam_id(steam_id_or_steam_friends_code: str) -> Optional[str]:
    if not steam_id_or_steam_friends_code.isdigit():
        return None

    id_ = int(steam_id_or_steam_friends_code)

    if id_ < STEAM_ID_OFFSET:
        return str(id_ + STEAM_ID_OFFSET)

    return steam_id_or_steam_friends_code


# ----------------------------
# Steam API
# ----------------------------
STEAM_BATCH_SIZE = 25

async def get_steam_users_info(
    steam_ids: List[str],
    api_key: str,
    proxy: Optional[str] = None,
) -> dict:
    if not steam_ids:
        return {"response": {"players": []}}

    all_players: List[dict] = []

    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
    timeout = httpx.Timeout(15.0)

    async with httpx.AsyncClient(
        proxy=proxy,
        timeout=timeout,
        headers={"User-Agent": "MadokaBot/SteamInfo"},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=5),
    ) as client:

        for i in range(0, len(steam_ids), STEAM_BATCH_SIZE):
            batch = steam_ids[i:i + STEAM_BATCH_SIZE]
            params = {
                "key": api_key,
                "steamids": ",".join(batch),
            }

            async def _fetch_once() -> bool:
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    raw = resp.json()
                    players = raw.get("response", {}).get("players", [])
                    for p in players:
                        all_players.append({
                            "steamid": p.get("steamid"),
                            "personaname": p.get("personaname"),
                            "personastate": p.get("personastate"),
                            "gameextrainfo": p.get("gameextrainfo"),
                            "avatar": p.get("avatar"),
                            "avatarfull": p.get("avatarfull"),
                            "lastlogoff": p.get("lastlogoff"),
                            "gameid": p.get("gameid"),
                            "communityvisibilitystate": p.get("communityvisibilitystate"),
                        })
                    return True
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                    logger.warning(f"Steam API 请求失败: {e}")
                    return False
                except Exception as e:
                    logger.error(f"Steam API 请求异常: {e}")
                    return False

            ok = await _fetch_once()
            if not ok:
                logger.warning("Steam API 重试一次")
                await _fetch_once()

            if i + STEAM_BATCH_SIZE < len(steam_ids):
                await asyncio.sleep(0.1)

    return {"response": {"players": all_players}}


# ----------------------------
# 通用 fetch
# ----------------------------
async def _fetch(
    url: str,
    default: bytes,
    cache_file: Optional[Path] = None,
    proxy: Optional[str] = None,
) -> bytes:
    if cache_file is not None and cache_file.exists():
        return cache_file.read_bytes()

    try:
        client = await get_http_client(proxy)
        response = await client.get(url)
        if response.status_code == 200:
            if cache_file is not None:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(response.content)
            return response.content
    except Exception as exc:
        logger.error(f"Failed to fetch image: {exc}")

    return default


# ----------------------------
# 用户详情
# ----------------------------
async def get_user_data(
    steam_id: int, cache_path: Path, proxy: Optional[str] = None
) -> PlayerData:
    url = f"https://steamcommunity.com/profiles/{steam_id}?l=schinese"
    default_background = default_background_path.read_bytes()
    default_avatar = default_avatar_path.read_bytes()
    default_achievement_image = default_achievement_image_path.read_bytes()
    default_header_image = default_header_image_path.read_bytes()

    result = {
        "description": "No information given.",
        "background": default_background,
        "avatar": default_avatar,
        "player_name": "Unknown",
        "recent_2_week_play_time": None,
        "game_data": [],
    }

    local_time = datetime.now(timezone.utc).astimezone()
    utc_offset_minutes = int(local_time.utcoffset().total_seconds())

    try:
        client = await get_http_client(proxy)
        response = await client.get(
            url,
            headers={
                "User-Agent": "MadokaBot/SteamInfo",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            cookies={
                "timezoneOffset": f"{utc_offset_minutes},0",
                "steamLanguage": "schinese",
                "wants_mature_content": "1",
            },
        )
        response.raise_for_status()
        html = response.text
    except Exception as exc:
        logger.error(f"获取用户详细数据失败: {exc}")
        return result

    player_name = re.search(r"<title>Steam 社区 :: (.*?)</title>", html)
    if player_name:
        result["player_name"] = player_name.group(1)

    description = re.search(
        r'<div class="profile_summary">(.*?)</div>', html, re.DOTALL
    )
    if description:
        desc = description.group(1)
        desc = re.sub(r"<br>", "\n", desc)
        desc = re.sub(r"\t", "", desc)
        desc = re.sub(r"ː.*?ː", "", desc)
        desc = re.sub(r"<.*?>", "", desc)
        result["description"] = desc.strip()

    soup = BeautifulSoup(html, "html.parser")
    game_data = []

    for game in soup.find_all("div", class_="recent_game"):
        game_info = {
            "game_name": game.find("div", class_="game_name").text.strip(),
            "achievements": [],
        }
        game_data.append(game_info)

    result["game_data"] = game_data
    return result
