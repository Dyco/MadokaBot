import hashlib
import re
from io import BytesIO
from urllib.parse import urljoin

import httpx
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image as PILImage
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
                timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0),
                headers={"User-Agent": "MadokaBot/SteamInfo"},
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    keepalive_expiry=30.0,
                    max_keepalive_connections=0,
                ),
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
            batch = steam_ids[i : i + STEAM_BATCH_SIZE]
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
                        all_players.append(
                            {
                                "steamid": p.get("steamid"),
                                "personaname": p.get("personaname"),
                                "personastate": p.get("personastate"),
                                "gameextrainfo": p.get("gameextrainfo"),
                                "avatar": p.get("avatar"),
                                "avatarfull": p.get("avatarfull"),
                                "lastlogoff": p.get("lastlogoff"),
                                "gameid": p.get("gameid"),
                                "communityvisibilitystate": p.get(
                                    "communityvisibilitystate"
                                ),
                            }
                        )
                    return True
                except (
                    httpx.ConnectError,
                    httpx.ReadTimeout,
                    httpx.RemoteProtocolError,
                ) as e:
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


def _is_valid_image_bytes(data: bytes) -> bool:
    if not data:
        return False
    try:
        image = PILImage.open(BytesIO(data))
        image.verify()
        return True
    except Exception:
        return False


async def _fetch(
    url: str,
    default: bytes,
    cache_file: Optional[Path] = None,
    proxy: Optional[str] = None,
) -> bytes:
    if cache_file is not None and cache_file.exists():
        cached = cache_file.read_bytes()
        if _is_valid_image_bytes(cached):
            return cached
        logger.warning(f"Cached Steam image is invalid, removing: {cache_file}")
        cache_file.unlink(missing_ok=True)

    try:
        client = await get_http_client(proxy)
        response = await client.get(url)
        if response.status_code == 200 and _is_valid_image_bytes(response.content):
            if cache_file is not None:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(response.content)
            return response.content
        logger.warning(
            "Steam image fetch returned invalid image "
            f"(status={response.status_code}, content-type={response.headers.get('content-type')}): {url}"
        )
    except Exception as exc:
        logger.error(f"Failed to fetch image: {exc}")

    return default


# ----------------------------
# 用户详情
# ----------------------------
def get_default_user_data(steam_id: Any) -> PlayerData:
    return {
        "steamid": str(steam_id),
        "description": "No information given.",
        "background": default_background_path.read_bytes(),
        "avatar": default_avatar_path.read_bytes(),
        "player_name": "Unknown",
        "recent_2_week_play_time": None,
        "game_data": [],
    }


async def get_user_data(
    steam_id: int, cache_path: Path, proxy: Optional[str] = None
) -> PlayerData:
    url = f"https://steamcommunity.com/profiles/{steam_id}?l=schinese"
    result = get_default_user_data(steam_id)
    default_background = result["background"]
    default_avatar = result["avatar"]
    default_achievement_image = default_achievement_image_path.read_bytes()
    default_header_image = default_header_image_path.read_bytes()

    result = {
        "steamid": str(steam_id),
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
        logger.error(f"获取用户详细数据失败，使用默认资料继续绘图: {exc}")
        return result

    soup = BeautifulSoup(html, "html.parser")

    if soup.title and soup.title.string:
        title = soup.title.string.strip()
        result["player_name"] = (
            re.sub(r"^Steam\s*(?:社区|Community)\s*::\s*", "", title).strip()
            or result["player_name"]
        )

    description_node = soup.select_one(".profile_summary")
    if description_node:
        for br in description_node.find_all("br"):
            br.replace_with("\n")
        desc = description_node.get_text("\n", strip=True)
        desc = re.sub(r"ː.*?ː", "", desc)
        result["description"] = desc.strip()

    background_url = _extract_background_url(html, soup)
    if background_url:
        result["background"] = await _fetch(
            background_url,
            default_background,
            _cache_file(cache_path, "backgrounds", background_url),
            proxy,
        )

    avatar_url = _extract_avatar_url(html, soup)
    if avatar_url:
        result["avatar"] = await _fetch(
            avatar_url,
            default_avatar,
            _cache_file(cache_path, "avatars", avatar_url),
            proxy,
        )

    recent_games_node = _find_recent_games_node(soup)
    result["recent_2_week_play_time"] = (
        _extract_recent_2_week_play_time(recent_games_node)
        or result["recent_2_week_play_time"]
    )

    game_data = []
    if recent_games_node:
        for game in recent_games_node.select(".recent_game"):
            game_info = await _parse_recent_game(
                game, default_header_image, default_achievement_image, cache_path, proxy
            )
            if game_info:
                game_data.append(game_info)

    result["game_data"] = game_data
    return result
