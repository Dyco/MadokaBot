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


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _node_text(node) -> str:
    return _clean_text(node.get_text("\n", strip=True) if node else "")


def _image_attr(node) -> Optional[str]:
    if not node:
        return None
    for attr in ("src", "data-src", "data-background-image", "href"):
        value = node.get(attr)
        if value:
            return value
    srcset = node.get("srcset")
    if srcset:
        return srcset.split(",")[-1].strip().split(" ")[0]
    return None


def _absolute_steam_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip().strip("\"'")
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin("https://steamcommunity.com/", url)


def _cache_file(cache_path: Path, category: str, url: str) -> Path:
    suffix = Path(url.split("?", 1)[0]).suffix or ".img"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return cache_path / "profile_assets" / category / f"{digest}{suffix}"


def _extract_background_url(html: str, soup: BeautifulSoup) -> Optional[str]:
    background_img = soup.select_one(
        ".profile_background_image_content img, "
        ".profile_background_holder_content img, "
        ".profile_animated_background img"
    )
    url = _absolute_steam_url(_image_attr(background_img))
    if url:
        return url

    for pattern in (
        r'<div[^>]+class=["\'][^"\']*profile_background_image_content[^"\']*["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']',
        r'profile_background_image_content[^<]+<img[^>]+src=["\']([^"\']+)["\']',
        r'background-image\s*:\s*url\(["\']?([^"\')]+)["\']?\)',
    ):
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return _absolute_steam_url(match.group(1))
    return None


def _extract_avatar_url(html: str, soup: BeautifulSoup) -> Optional[str]:
    avatar_candidates = soup.select(
        ".playerAvatarAutoSizeInner img, .playerAvatar img, .profile_header .playerAvatar img"
    )
    for image in avatar_candidates:
        url = _absolute_steam_url(_image_attr(image))
        if url and ("avatars" in url or "avatar" in url):
            return url

    match = re.search(r'https?://[^"\']*/avatars/[^"\']+_full\.(?:jpg|png|gif)', html)
    if match:
        return match.group(0)
    return None


def _extract_recent_2_week_play_time(recent_node) -> Optional[str]:
    if not recent_node:
        return None
    text = _node_text(recent_node)
    match = re.search(r"([\d,.]+\s*小时\s*[（(]\s*过去\s*2\s*周\s*[）)])", text)
    if match:
        return _clean_text(match.group(1))
    match = re.search(r"([\d,.]+\s*hrs?\s+past\s+2\s+weeks)", text, re.IGNORECASE)
    if match:
        return _clean_text(match.group(1))
    return None


async def _parse_recent_game(
    game,
    default_header_image: bytes,
    default_achievement_image: bytes,
    cache_path: Path,
    proxy: Optional[str],
) -> Optional[dict]:
    name_node = game.select_one(".game_name a, .game_name")
    game_name = _node_text(name_node)
    if not game_name:
        return None

    header_url = _absolute_steam_url(
        _image_attr(game.select_one(".game_info_cap img, img[src*='capsule_184x69']"))
    )
    game_image = default_header_image
    if header_url:
        game_image = await _fetch(
            header_url,
            default_header_image,
            _cache_file(cache_path, "game_headers", header_url),
            proxy,
        )

    details_text = _node_text(
        game.select_one(".game_info_details_block, .game_info_stats") or game
    )
    play_time = "0"
    play_time_match = re.search(
        r"(?:总时数|Total\s+Playtime|Total\s+hours)\s*([\d,.]+)\s*(?:小时|hrs?|hours?)?",
        details_text,
        re.IGNORECASE,
    )
    if play_time_match:
        play_time = play_time_match.group(1)

    last_played = "未知"
    last_played_match = re.search(
        r"(?:最后运行日期|Last\s+Played)\s*[：:]\s*(.+)$",
        details_text,
        re.IGNORECASE,
    )
    if last_played_match:
        last_played = _clean_text(last_played_match.group(1))

    completed_achievement_number = 0
    total_achievement_number = 0
    achievement_match = re.search(r"(\d+)\s*/\s*(\d+)", _node_text(game))
    if achievement_match:
        completed_achievement_number = int(achievement_match.group(1))
        total_achievement_number = int(achievement_match.group(2))

    achievements = []
    seen_achievement_urls = set()
    achievement_images = game.select(
        ".recent_game_achievements img, "
        ".game_info_achievement img, "
        ".achievement_icon img, "
        "a[href*='achievements'] img"
    )
    for image in achievement_images[:6]:
        image_url = _absolute_steam_url(_image_attr(image))
        if (
            not image_url
            or image_url == header_url
            or image_url in seen_achievement_urls
        ):
            continue
        seen_achievement_urls.add(image_url)
        achievements.append(
            {
                "name": image.get("alt") or image.get("title") or "",
                "image": await _fetch(
                    image_url,
                    default_achievement_image,
                    _cache_file(cache_path, "achievement_icons", image_url),
                    proxy,
                ),
            }
        )

    return {
        "game_name": game_name,
        "play_time": play_time,
        "last_played": last_played,
        "game_image": game_image,
        "achievements": achievements,
        "completed_achievement_number": completed_achievement_number,
        "total_achievement_number": total_achievement_number,
    }


def _find_recent_games_node(soup: BeautifulSoup):
    recent_node = soup.select_one(".recent_games")
    if recent_node:
        return recent_node
    header = soup.find(string=re.compile(r"最新动态|Recent Activity", re.IGNORECASE))
    if not header:
        return None
    for parent in header.parents:
        if parent.select(".recent_game"):
            return parent
    return None


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

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.error(f"解析 Steam 主页 HTML 失败，使用默认资料继续绘图: {exc}")
        return result

    try:
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            result["player_name"] = (
                re.sub(r"^Steam\s*(?:社区|Community)\s*::\s*", "", title).strip()
                or result["player_name"]
            )
    except Exception as exc:
        logger.warning(f"解析 Steam 玩家名称失败: {exc}")

    try:
        description_node = soup.select_one(".profile_summary")
        if description_node:
            for br in description_node.find_all("br"):
                br.replace_with("\n")
            desc = description_node.get_text("\n", strip=True)
            desc = re.sub(r"ː.*?ː", "", desc)
            result["description"] = desc.strip()
    except Exception as exc:
        logger.warning(f"解析 Steam 玩家简介失败: {exc}")

    try:
        background_url = _extract_background_url(html, soup)
        if background_url:
            result["background"] = await _fetch(
                background_url,
                default_background,
                _cache_file(cache_path, "backgrounds", background_url),
                proxy,
            )
    except Exception as exc:
        logger.warning(f"解析 Steam 背景图失败，使用默认背景继续绘图: {exc}")

    try:
        avatar_url = _extract_avatar_url(html, soup)
        if avatar_url:
            result["avatar"] = await _fetch(
                avatar_url,
                default_avatar,
                _cache_file(cache_path, "avatars", avatar_url),
                proxy,
            )
    except Exception as exc:
        logger.warning(f"解析 Steam 头像失败，使用默认头像继续绘图: {exc}")

    try:
        recent_games_node = _find_recent_games_node(soup)
    except Exception as exc:
        logger.warning(f"定位 Steam 最近游戏区域失败: {exc}")
        recent_games_node = None

    try:
        result["recent_2_week_play_time"] = (
            _extract_recent_2_week_play_time(recent_games_node)
            or result["recent_2_week_play_time"]
        )
    except Exception as exc:
        logger.warning(f"解析 Steam 最近两周游戏时间失败: {exc}")

    game_data = []
    if recent_games_node:
        for game in recent_games_node.select(".recent_game"):
            try:
                game_info = await _parse_recent_game(
                    game,
                    default_header_image,
                    default_achievement_image,
                    cache_path,
                    proxy,
                )
            except Exception as exc:
                logger.warning(f"解析 Steam 最近游戏条目失败，已跳过该条目: {exc}")
                continue
            if game_info:
                game_data.append(game_info)

    result["game_data"] = game_data
    return result
