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
_http_clients: Dict[Optional[str], Tuple[httpx.AsyncClient, float]] = {}
_http_client_lock = asyncio.Lock()
HTTP_CLIENT_MAX_AGE = 60 * 30


async def get_http_client(proxy: Optional[str]) -> httpx.AsyncClient:
    async with _http_client_lock:
        now = time.time()
        client_entry = _http_clients.get(proxy)
        if client_entry is not None:
            client, created_at = client_entry
            if not client.is_closed and now - created_at <= HTTP_CLIENT_MAX_AGE:
                return client
            if not client.is_closed:
                try:
                    await client.aclose()
                except Exception:
                    pass

        client = httpx.AsyncClient(
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
        _http_clients[proxy] = (client, now)
        logger.info("Steam HTTP client recreated for the requested proxy mode")

        return client


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
            logger.info(f"Steam image cache hit: {cache_file}")
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
                logger.info(f"Steam image cached: {cache_file}")
            return response.content
        logger.warning(
            "Steam image fetch returned invalid image "
            f"(status={response.status_code}, content-type={response.headers.get('content-type')}): {url}"
        )
    except Exception as exc:
        logger.error(f"Failed to fetch image: {exc}")

    return default


def _url_from_attr(node, *attrs: str) -> Optional[str]:
    for attr in attrs:
        value = node.get(attr)
        if isinstance(value, str) and value.strip():
            return value.strip()
    srcset = node.get("srcset")
    if isinstance(srcset, str) and srcset.strip():
        # Prefer the largest candidate, which Steam usually lists last.
        return srcset.split(",")[-1].strip().split()[0]
    return None


def _normalize_steam_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip().strip('"\'')
    if not url or url.startswith("data:"):
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return urljoin("https://steamcommunity.com/", url)


def _style_image_url(style: Optional[str]) -> Optional[str]:
    if not style:
        return None
    match = re.search(r"url\((['\"]?)(.*?)\1\)", style, re.I | re.S)
    if not match:
        return None
    return _normalize_steam_url(match.group(2))


def _cache_file(cache_path: Path, category: str, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    ext_match = re.search(r"\.([a-zA-Z0-9]{2,5})(?:[?#].*)?$", url)
    ext = f".{ext_match.group(1).lower()}" if ext_match else ".img"
    return cache_path / category / f"{digest}{ext}"


def _extract_background_url(html: str, soup: BeautifulSoup) -> Optional[str]:
    # The reference page stores the equipped static background on the main
    # profile-page container. Read that exact element first so decoration,
    # preview, and avatar-frame assets cannot be mistaken for the background.
    profile_page = soup.select_one(
        ".no_header.profile_page.has_profile_background"
        "[style*='background-image']"
    )
    if profile_page:
        url = _style_image_url(profile_page.get("style"))
        if url:
            return url

    # Match Sample.py's `background-image: url( '...' )` structure when the
    # profile classes differ, allowing harmless whitespace/quote variations.
    match = re.search(
        r"background-image\s*:\s*url\(\s*(['\"])(.*?)\1\s*\)",
        html,
        re.I | re.S,
    )
    if match:
        return _normalize_steam_url(match.group(2))

    # Animated backgrounds have no usable static background-image. Prefer their
    # poster frame rather than selecting an unrelated image from a broad class
    # match.
    animated_background = soup.select_one(
        ".profile_animated_background video[poster], "
        "video.profile_animated_background[poster]"
    )
    if animated_background:
        return _normalize_steam_url(animated_background.get("poster"))

    return None


def _extract_avatar_url(html: str, soup: BeautifulSoup) -> Optional[str]:
    # Steam's profile page exposes the canonical full-size avatar through this
    # link even when the visible avatar markup changes (see Sample.py).
    image_src = soup.find("link", rel="image_src")
    if image_src:
        url = _normalize_steam_url(image_src.get("href"))
        if url:
            return url

    selectors = (
        ".playerAvatarAutoSizeInner img",
        ".profile_header .playerAvatar img",
        ".profile_header .playerAvatarAutoSizeInner img",
        "img.playerAvatarAutoSizeInner",
        ".profile_avatar_frame img",
    )
    for selector in selectors:
        for image in soup.select(selector):
            url = _normalize_steam_url(_url_from_attr(image, "src", "data-src"))
            if url and "avatar_frame" not in url:
                return url

    match = re.search(r"https?://[^'\"]+/avatars/[^'\"]+_full\.jpg", html, re.I)
    if match:
        return match.group(0)
    return None


def _find_recent_games_node(soup: BeautifulSoup):
    for selector in ("#recent_games", ".recent_games"):
        node = soup.select_one(selector)
        if node:
            return node

    recent_game = soup.select_one(".recent_game")
    if not recent_game:
        return None
    parent = recent_game.parent
    while parent is not None and parent.name not in ("body", "html"):
        if parent.select_one(".recent_game"):
            return parent
        parent = parent.parent
    return recent_game.parent


def _extract_recent_2_week_play_time(soup: BeautifulSoup) -> Optional[str]:
    # This is the stable structure used by the reference implementation.
    play_time_node = soup.select_one(
        ".recentgame_quicklinks.recentgame_recentplaytime > div"
    )
    if play_time_node:
        value = play_time_node.get_text(" ", strip=True)
        if value:
            return value

    recent_games_node = _find_recent_games_node(soup)
    if not recent_games_node:
        return None
    text = recent_games_node.get_text(" ", strip=True)
    patterns = (
        r"过去\s*2\s*周(?:总时数|共)?\s*([\d,.]+\s*小时)",
        r"Past\s*2\s*weeks\s*([\d,.]+\s*hrs?)",
        r"([\d,.]+\s*小时)\s*(?:过去\s*2\s*周|最近\s*2\s*周)",
        r"([\d,.]+\s*hrs?)\s*(?:past\s*2\s*weeks|last\s*2\s*weeks)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1).replace("hrs", "小时").replace("hr", "小时")
    return None


def _extract_text_by_patterns(text: str, patterns: Tuple[str, ...]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def _extract_first_image_url(node, selectors: Tuple[str, ...]) -> Optional[str]:
    for selector in selectors:
        for image in node.select(selector):
            url = _normalize_steam_url(_url_from_attr(image, "src", "data-src"))
            if url:
                return url
    return None


async def _parse_recent_game(
    game,
    default_header_image: bytes,
    default_achievement_image: bytes,
    cache_path: Path,
    proxy: Optional[str],
) -> Optional[dict]:
    text = game.get_text(" ", strip=True)
    if not text:
        return None

    name_node = game.select_one(
        ".game_name a, .game_name, .recent_game_name, .game_info_name, a[href*='/app/']"
    )
    game_name = name_node.get_text(" ", strip=True) if name_node else "未知游戏"

    details_node = game.select_one(".game_info_details")
    details_text = details_node.get_text(" ", strip=True) if details_node else text

    # Keep only the numeric portion. The drawing adapter adds the Chinese unit,
    # matching the field contract used by Sample.py.
    play_time = _extract_text_by_patterns(
        details_text,
        (
            r"总时数\s*([\d,.]+)\s*小时",
            r"Total\s*Play(?:ed)?\s*([\d,.]+)\s*(?:hrs?|hours?)",
            r"([\d,.]+)\s*小时\s*总时数",
            r"([\d,.]+)\s*(?:hrs?|hours?)\s*on\s*record",
        ),
    ) or ""

    last_played_value = _extract_text_by_patterns(
        details_text,
        (
            r"最后(?:运行|游玩)日期[：:]?\s*(.*?)(?:\s+成就|$)",
            r"Last\s*Played[：:]?\s*(.*?)(?:\s+Achievements|$)",
        ),
    )
    last_played = (
        f"最后运行日期：{last_played_value}"
        if last_played_value
        else "当前正在游戏"
    )

    header_url = _extract_first_image_url(
        game,
        (
            "img.game_capsule",
            "img[src*='header']",
            "img[src*='capsule_184x69']",
            ".game_capsule img",
            ".game_info_cap img",
            "img",
        ),
    )
    game_image = default_header_image
    if header_url:
        game_image = await _fetch(
            header_url,
            default_header_image,
            _cache_file(cache_path, "game_headers", header_url),
            proxy,
        )

    completed_achievement_number = 0
    total_achievement_number = 0
    achievement_summary = game.select_one(
        ".game_info_achievement_summary .ellipsis, "
        ".game_info_achievement_summary"
    )
    achievement_text = (
        achievement_summary.get_text(" ", strip=True)
        if achievement_summary
        else text
    )
    achievement_match = re.search(r"(\d+)\s*/\s*(\d+)", achievement_text)
    if achievement_match:
        completed_achievement_number = int(achievement_match.group(1))
        total_achievement_number = int(achievement_match.group(2))

    achievements = []
    seen_urls = set()
    for image in game.select(
        ".game_info_achievement:not(.plus_more) img, "
        ".achievement img, .achieveImgHolder img, img[src*='achievements']"
    ):
        achievement_node = image.find_parent(
            class_=lambda classes: classes
            and "game_info_achievement" in classes
        )
        if achievement_node and "plus_more" in achievement_node.get("class", []):
            continue

        url = _normalize_steam_url(_url_from_attr(image, "src", "data-src"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        achievements.append(
            {
                "name": (
                    achievement_node.get("data-tooltip-text")
                    if achievement_node
                    else None
                )
                or image.get("alt")
                or image.get("title")
                or "",
                "image": await _fetch(
                    url,
                    default_achievement_image,
                    _cache_file(cache_path, "achievements", url),
                    proxy,
                ),
            }
        )
        if len(achievements) >= 6:
            break

    return {
        "game_name": game_name,
        "play_time": play_time,
        "last_played": last_played,
        "game_image": game_image,
        "achievements": achievements,
        "completed_achievement_number": completed_achievement_number,
        "total_achievement_number": total_achievement_number,
    }


# ----------------------------
# 用户详情
# ----------------------------
def get_default_user_data(steam_id: Any) -> PlayerData:
    return {
        "steamid": str(steam_id),
        "description": "No information given.",
        "background": default_background_path.read_bytes(),
        "avatar": default_avatar_path.read_bytes(),
        "avatar_frame": None,
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
        "avatar_frame": None,
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
        for h1 in description_node.select(".bb_h1"):
            h1.replace_with(f"[H1]{h1.get_text(' ', strip=True)}[/H1]")
        desc = description_node.get_text("\n", strip=True)
        desc = re.sub(r"ː.*?ː", "", desc)
        result["description"] = desc.strip()

    background_url = _extract_background_url(html, soup)
    if background_url:
        logger.info(f"Steam profile background URL extracted: {background_url}")
        result["background"] = await _fetch(
            background_url,
            default_background,
            _cache_file(cache_path, "backgrounds", background_url),
            proxy,
        )
    else:
        logger.info("Steam profile background URL not found; using default background")

    avatar_url = _extract_avatar_url(html, soup)
    if avatar_url:
        logger.info(f"Steam profile avatar URL extracted: {avatar_url}")
        result["avatar"] = await _fetch(
            avatar_url,
            default_avatar,
            _cache_file(cache_path, "avatars", avatar_url),
            proxy,
        )
    else:
        logger.info("Steam profile avatar URL not found; using default avatar")

    result["recent_2_week_play_time"] = (
        _extract_recent_2_week_play_time(soup)
        or result["recent_2_week_play_time"]
    )

    game_data = []
    # Parse cards directly from the page. A `recentgame_quicklinks` element is
    # inside a card, so treating it as the list container drops every game.
    for game in soup.select("div.recent_game"):
        game_info = await _parse_recent_game(
            game, default_header_image, default_achievement_image, cache_path, proxy
        )
        if game_info:
            game_data.append(game_info)

    result["game_data"] = game_data
    return result
