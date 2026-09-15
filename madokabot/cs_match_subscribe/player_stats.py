"""5E 与完美平台的账号绑定及聚合战绩查询。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from .config import PLAYER_BINDINGS_PATH, PW_SESSION_PATH, config


FIVE_E_SEARCH_URL = "https://arena.5eplay.com/api/search/player/1/16"
FIVE_E_ID_URL = "https://gate.5eplay.com/userinterface/http/v1/userinterface/idTransfer"
FIVE_E_CAREER_URL = "https://gate.5eplay.com/crane/http/api/data/player_career"
FIVE_E_MATCH_URL = "https://gate.5eplay.com/crane/http/api/data/player_match"
FIVE_E_PLAYER_URL = "https://arena.5eplay.com/api/data/player"
PW_SEARCH_URL = "https://appengine.wmpvp.com/steamcn/app/search/user"
PW_STATS_URL = "https://api.wmpvp.com/api/csgo/home/pvp/detailStats"
PW_MATCHES_URL = "https://api.wmpvp.com/api/csgo/home/match/list"

PLATFORM_ALIASES = {
    "5e": "5e",
    "pw": "pw",
    "完美": "pw",
    "完美世界": "pw",
}


class PlayerStatsError(RuntimeError):
    """平台战绩接口或参数不可用。"""


@dataclass(slots=True)
class PlayerBinding:
    """一个 QQ 用户在某个平台绑定的查询对象。"""

    user_id: str
    platform: str
    player_name: str
    domain: str = ""
    uuid: str = ""
    avatar_url: str = ""


class PlayerBindingStore:
    """使用独立 SQLite 文件保存平台绑定，避免混入赛事订阅 JSON。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """打开绑定数据库连接。"""
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        """初始化绑定表结构。"""
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS player_bindings (
                    user_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    uuid TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, platform)
                )
                """
            )
            connection.commit()

    def save(self, binding: PlayerBinding) -> PlayerBinding:
        """新增或覆盖一个平台绑定。"""
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO player_bindings
                    (user_id, platform, player_name, domain, uuid, avatar_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, platform) DO UPDATE SET
                    player_name=excluded.player_name,
                    domain=excluded.domain,
                    uuid=excluded.uuid,
                    avatar_url=excluded.avatar_url,
                    updated_at=excluded.updated_at
                """,
                (
                    binding.user_id,
                    binding.platform,
                    binding.player_name,
                    binding.domain,
                    binding.uuid,
                    binding.avatar_url,
                    int(time.time()),
                ),
            )
            connection.commit()
        return binding

    def get(self, user_id: str, platform: str) -> PlayerBinding | None:
        """读取一个 QQ 用户的平台绑定。"""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_id, platform, player_name, domain, uuid, avatar_url
                FROM player_bindings
                WHERE user_id = ? AND platform = ?
                """,
                (str(user_id), platform),
            ).fetchone()
        return PlayerBinding(**dict(row)) if row else None


binding_store = PlayerBindingStore(PLAYER_BINDINGS_PATH)


def normalize_platform(value: str | None) -> str | None:
    """将 5E、PW、完美等输入统一为内部平台名称。"""
    if not value:
        return None
    return PLATFORM_ALIASES.get(value.strip().casefold())


def platform_label(platform: str) -> str:
    """返回适合消息和卡片展示的平台名称。"""
    return "5E" if platform == "5e" else "完美世界"


def _proxy() -> str | None:
    """返回平台接口请求使用的代理。"""
    value = config.hltv_proxy or madoka_config.proxy
    if value is None:
        return None
    proxy = str(value).strip()
    if not proxy:
        return None
    return proxy if "://" in proxy else f"http://{proxy}"


def _client() -> httpx.AsyncClient:
    """创建平台接口共用的 HTTP 客户端。"""
    return httpx.AsyncClient(
        proxy=_proxy(),
        trust_env=False,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            )
        },
        timeout=httpx.Timeout(config.hltv_request_timeout, connect=10.0),
    )


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """请求 JSON 接口，并把网络错误统一转换为业务异常。"""
    try:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise PlayerStatsError(
            f"平台接口返回 HTTP {exc.response.status_code}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise PlayerStatsError(f"平台接口请求失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise PlayerStatsError("平台接口返回格式异常")
    return payload


def _dict(value: Any) -> dict[str, Any]:
    """只保留字典类型的接口字段。"""
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    """只保留列表类型的接口字段。"""
    return value if isinstance(value, list) else []


def _value(source: dict[str, Any], *keys: str) -> Any:
    """按候选键读取第一个非空接口字段。"""
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    """把接口数字转换为浮点数。"""
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    """把接口数字转换为整数。"""
    number = _float(value)
    return int(number) if number is not None else None


def _number_text(value: Any, places: int = 2) -> str:
    """把数值格式化为卡片文本。"""
    number = _float(value)
    return "-" if number is None else f"{number:.{places}f}"


def _percent_text(value: Any) -> str:
    """把比例或百分数统一格式化为百分比文本。"""
    number = _float(value)
    if number is None:
        return "-"
    if number <= 1:
        number *= 100
    return f"{number:.1f}%"


def _flag(value: Any) -> bool:
    """识别平台接口中的布尔字段。"""
    return value is True or str(value).strip().casefold() in {"1", "true", "yes"}


def _image_url(value: Any) -> str:
    """补全平台返回的头像地址。"""
    url = str(value or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url and not url.startswith(("http://", "https://", "data:")):
        return f"https://oss-arena.5eplay.com/{url.lstrip('/')}"
    return url


async def _search_5e_player(
    client: httpx.AsyncClient,
    nickname: str,
) -> dict[str, str]:
    """通过 5E 搜索接口选择精确昵称，否则选择首个结果。"""
    payload = await _request_json(
        client,
        "GET",
        FIVE_E_SEARCH_URL,
        params={"keywords": nickname},
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://arena.5eplay.com/search?keywords={nickname}",
        },
    )
    user_data = _dict(_dict(payload.get("data")).get("user"))
    candidates = []
    for item in _list(user_data.get("list")):
        user = _dict(item)
        name = str(user.get("username") or user.get("name") or "").strip()
        domain = str(user.get("domain") or "").strip()
        if name and domain:
            candidates.append(
                {
                    "name": name,
                    "domain": domain,
                    "avatar": _image_url(user.get("avatar_url") or user.get("avatar")),
                }
            )
    if not candidates:
        raise PlayerStatsError(f"未找到 5E 玩家：{nickname}")
    nickname_key = nickname.casefold()
    return next(
        (item for item in candidates if item["name"].casefold() == nickname_key),
        candidates[0],
    )


async def _resolve_5e_uuid(
    client: httpx.AsyncClient,
    domain: str,
) -> str:
    """将 5E 玩家域名转换为战绩接口所需的 UUID。"""
    payload = await _request_json(
        client,
        "POST",
        FIVE_E_ID_URL,
        json={"trans": {"domain": domain}},
    )
    uuid = str(_dict(payload.get("data")).get("uuid") or "").strip()
    if not uuid:
        raise PlayerStatsError("5E 玩家 UUID 获取失败")
    return uuid


async def _resolve_5e_identity(nickname: str) -> PlayerBinding:
    """根据 5E 昵称解析可查询的玩家绑定。"""
    async with _client() as client:
        result = await _search_5e_player(client, nickname)
        uuid = await _resolve_5e_uuid(client, result["domain"])
    return PlayerBinding(
        user_id="",
        platform="5e",
        player_name=result["name"],
        domain=result["domain"],
        uuid=uuid,
        avatar_url=result["avatar"],
    )


def _pw_session_path() -> Path:
    """返回完美平台会话文件路径。"""
    configured = str(config.cs_pw_session_path or "").strip()
    return Path(configured) if configured else PW_SESSION_PATH


def _load_pw_session() -> dict[str, Any]:
    """读取完美平台会话文件；登录流程后续再单独实现。"""
    path = _pw_session_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    token = str(raw.get("token") or "").strip()
    steam_id = _int(raw.get("steam_id") or raw.get("my_steam_id"))
    return {
        "token": token,
        "my_steam_id": steam_id or 0,
        "appversion": str(raw.get("appversion") or "3.5.4.172"),
    } if token and steam_id else {}


def _pw_headers(session: dict[str, Any]) -> dict[str, str]:
    """生成完美平台接口请求头。"""
    return {
        "appversion": str(session["appversion"]),
        "token": str(session["token"]),
        "platform": "android",
        "Content-Type": "application/json",
    }


async def _resolve_pw_identity(nickname: str) -> PlayerBinding:
    session = _load_pw_session()
    if not session:
        raise PlayerStatsError(
            "完美平台绑定需要登录态；当前已支持记录昵称，查询前请配置 pw_session.json"
        )

    async with _client() as client:
        payload = await _request_json(
            client,
            "POST",
            PW_SEARCH_URL,
            headers=_pw_headers(session),
            json={"keyword": nickname, "page": 1},
        )
    if payload.get("code") != 1:
        raise PlayerStatsError(str(payload.get("description") or "完美平台搜索失败"))

    candidates = []
    for item in _list(payload.get("result")):
        user = _dict(item)
        name = str(
            user.get("pvpNickName") or user.get("name") or user.get("steamNick") or ""
        ).strip()
        steam_id = str(user.get("steamId") or user.get("steam_id") or "").strip()
        if name and steam_id:
            candidates.append(
                PlayerBinding(
                    user_id="",
                    platform="pw",
                    player_name=name,
                    domain=str(user.get("pvpUserId") or "").strip(),
                    uuid=steam_id,
                    avatar_url=_image_url(user.get("avatar") or user.get("avatarUrl")),
                )
            )
    if not candidates:
        raise PlayerStatsError(f"未找到完美玩家：{nickname}")
    nickname_key = nickname.casefold()
    return next(
        (item for item in candidates if item.player_name.casefold() == nickname_key),
        candidates[0],
    )


async def bind_player(user_id: str, platform: str, nickname: str) -> PlayerBinding:
    """解析并保存 5E/PW 昵称绑定。"""
    normalized = normalize_platform(platform)
    name = nickname.strip()
    if normalized is None or normalized not in {"5e", "pw"}:
        raise PlayerStatsError("平台仅支持 5e、5E、pw、PW 或 完美")
    if not name:
        raise PlayerStatsError("缺少玩家昵称")

    if normalized == "5e":
        binding = await _resolve_5e_identity(name)
    elif _load_pw_session():
        binding = await _resolve_pw_identity(name)
    else:
        # 没有完美平台会话时仍保留用户明确输入的昵称，方便后续补齐 ID。
        binding = PlayerBinding(
            user_id="",
            platform="pw",
            player_name=name,
        )
    binding.user_id = str(user_id)
    return binding_store.save(binding)


def get_binding(user_id: str, platform: str) -> PlayerBinding | None:
    """读取当前用户已经绑定的平台账号。"""
    normalized = normalize_platform(platform)
    return binding_store.get(str(user_id), normalized) if normalized else None


async def _fetch_5e_stats(binding: PlayerBinding) -> dict[str, Any]:
    """请求 5E 生涯、近期比赛和玩家资料。"""
    async with _client() as client:
        career_result, matches_result, arena_result = await asyncio.gather(
            _request_json(client, "GET", FIVE_E_CAREER_URL, params={"uuid": binding.uuid}),
            _request_json(client, "GET", FIVE_E_MATCH_URL, params={"uuid": binding.uuid}),
            _request_json(client, "GET", f"{FIVE_E_PLAYER_URL}/{binding.domain}"),
            return_exceptions=True,
        )

    career_payload = career_result if isinstance(career_result, dict) else {}
    matches_payload = matches_result if isinstance(matches_result, dict) else {}
    arena_payload = arena_result if isinstance(arena_result, dict) else {}
    career_data = _dict(_dict(career_payload.get("data")).get("career_data"))
    match_data = _list(_dict(matches_payload.get("data")).get("match_data"))
    arena_data = _dict(arena_payload.get("data"))
    if not career_data and not arena_data:
        error = next(
            (item for item in (career_result, arena_result) if isinstance(item, Exception)),
            None,
        )
        raise PlayerStatsError(str(error or "未找到有效的 5E 战绩数据"))

    for source_key, target_key in (
        ("headshot", "headshot_total"),
        ("kill", "kill_total"),
        ("per_headshot", "per_headshot"),
    ):
        if target_key not in career_data and arena_data.get(source_key) not in (None, ""):
            career_data[target_key] = arena_data[source_key]

    return _build_5e_view(binding, career_data, match_data)


def _build_5e_view(
    binding: PlayerBinding,
    career: dict[str, Any],
    matches: list[Any],
) -> dict[str, Any]:
    """把 5E 原始数据转换为统一卡片上下文。"""
    kills = _int(_value(career, "kill_total", "kills", "kill")) or 0
    deaths = _int(_value(career, "death_total", "deaths", "death")) or 0
    total = _int(_value(career, "match_total", "matches", "cnt")) or 0
    wins = _int(_value(career, "win_total", "wins", "win")) or 0
    ties = _int(_value(career, "tie_total", "ties", "tie")) or 0
    losses = _int(_value(career, "loss_total", "losses", "loss"))
    if losses is None:
        losses = max(total - wins - ties, 0)
    win_rate = _value(career, "win_rate", "winRate")
    if win_rate is None and total:
        win_rate = wins / total
    headshots = _int(_value(career, "headshot_total", "headshots", "headshot"))
    headshot_rate = (
        (headshots / kills) if headshots is not None and kills else
        _value(career, "per_headshot", "headshot_rate", "headshotRate")
    )
    kd = _value(career, "kd", "k_d")
    if kd is None and deaths:
        kd = kills / deaths
    kpr = _value(career, "kpr", "kills_per_round")
    return _build_view(
        platform="5e",
        platform_name="5E",
        accent="#f47b20",
        binding=binding,
        identity_label="5E ID",
        hero_label="综合 Rating",
        hero_value=_number_text(_value(career, "rating", "rating2")),
        summary=[
            {"label": "总场次", "value": str(total)},
            {"label": "综合胜率", "value": _percent_text(win_rate)},
            {"label": "当前 ELO", "value": str(_value(career, "elo_9", "elo") or "-")},
            {"label": "胜 / 平 / 负", "value": f"{wins} / {ties} / {losses}"},
        ],
        metrics=[
            {"label": "ADR", "value": _number_text(_value(career, "adr"), 1), "note": "平均每回合伤害"},
            {"label": "K / D", "value": _number_text(kd), "note": f"{kills}K / {deaths}D"},
            {"label": "KPR", "value": _number_text(kpr), "note": "场均击杀"},
            {"label": "爆头率", "value": _percent_text(headshot_rate), "note": "击杀中的爆头比例"},
            {"label": "RWS", "value": _number_text(_value(career, "rws")), "note": "胜局贡献"},
            {"label": "全服排名", "value": str(_value(career, "rank") or "-"), "note": "Ladder Rank"},
        ],
        recent_matches=[_build_5e_match_view(_dict(item)) for item in matches[:5]],
    )


def _build_5e_match_view(match: dict[str, Any]) -> dict[str, str]:
    """把一条 5E 近期比赛转换为卡片数据。"""
    is_win = _flag(_value(match, "is_win", "isWin"))
    is_tie = _flag(_value(match, "is_tie", "isTie"))
    score = _value(match, "score")
    if not score:
        score1 = _value(match, "group1_all_score", "score1")
        score2 = _value(match, "group2_all_score", "score2")
        score = f"{score1}:{score2}" if score1 is not None and score2 is not None else "-"
    result_text = "胜利" if is_win else ("平局" if is_tie else "失败")
    result_class = "win" if is_win else ("draw" if is_tie else "loss")
    kills = _value(match, "kill", "kills")
    deaths = _value(match, "death", "deaths")
    adr = _value(match, "adr")
    return {
        "result_text": result_text,
        "result_class": result_class,
        "map_name": str(_value(match, "map_name", "map") or "未知地图"),
        "score": str(score),
        "rating": _number_text(_value(match, "rating", "pw_rating")),
        "details": f"{kills or '-'}K / {deaths or '-'}D · ADR {_number_text(adr, 1)}",
    }


async def _fetch_pw_stats(binding: PlayerBinding) -> dict[str, Any]:
    """请求完美平台聚合战绩和近期比赛。"""
    session = _load_pw_session()
    if not session:
        raise PlayerStatsError(
            "完美平台查询需要登录态，请配置 pw_session.json 后再查询"
        )
    target_id = _int(binding.uuid)
    if not target_id:
        raise PlayerStatsError("完美玩家 SteamID 无效")

    headers = _pw_headers(session)
    async with _client() as client:
        payload = await _request_json(
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
        stats = _dict(payload.get("data"))
        if not stats:
            raise PlayerStatsError("未找到有效的完美平台战绩数据")

        recent_matches: list[Any] = []
        try:
            recent_payload = await _request_json(
                client,
                "POST",
                PW_MATCHES_URL,
                headers=headers,
                json={
                    "csgoSeasonId": "recent",
                    "dataSource": 3,
                    "mySteamId": int(session["my_steam_id"]),
                    "page": 1,
                    "pageSize": 5,
                    "pvpType": -1,
                    "toSteamId": target_id,
                },
            )
            recent_matches = _list(_dict(recent_payload.get("data")).get("matchList"))
        except PlayerStatsError as exc:
            logger.warning("完美平台近期比赛获取失败：%s", exc)

    summary = {
        "nickname": str(stats.get("name") or binding.player_name),
        "avatar": _image_url(stats.get("avatar")),
        "steam_id": str(stats.get("steamId") or binding.uuid),
    }
    binding.player_name = summary["nickname"]
    binding.avatar_url = binding.avatar_url or summary["avatar"]
    return _build_pw_view(binding, stats, recent_matches)


def _build_pw_view(
    binding: PlayerBinding,
    stats: dict[str, Any],
    matches: list[Any],
) -> dict[str, Any]:
    """把完美平台原始数据转换为统一卡片上下文。"""
    kills = _int(_value(stats, "kills", "kill")) or 0
    deaths = _int(_value(stats, "deaths", "death")) or 0
    kd = _value(stats, "kd")
    if kd is None and deaths:
        kd = kills / deaths
    total = _int(_value(stats, "cnt", "matchCount", "totalMatch", "matches")) or 0
    wins = _int(_value(stats, "winCount", "wins", "win_total")) or 0
    ties = _int(_value(stats, "tieCount", "ties", "tie_total")) or 0
    losses = _int(_value(stats, "lossCount", "losses", "loss_total"))
    if losses is None:
        losses = max(total - wins - ties, 0)
    return _build_view(
        platform="pw",
        platform_name="完美世界",
        accent="#5b7cff",
        binding=binding,
        identity_label="SteamID",
        hero_label="综合 Rating",
        hero_value=_number_text(_value(stats, "pwRating", "rating")),
        summary=[
            {"label": "总场次", "value": str(total)},
            {"label": "综合胜率", "value": _percent_text(_value(stats, "winRate"))},
            {"label": "天梯分数", "value": str(_value(stats, "pvpScore") or "-")},
            {"label": "胜 / 平 / 负", "value": f"{wins} / {ties} / {losses}"},
        ],
        metrics=[
            {"label": "ADR", "value": _number_text(_value(stats, "adr"), 1), "note": "平均每回合伤害"},
            {"label": "K / D", "value": _number_text(kd), "note": f"{kills}K / {deaths}D"},
            {"label": "爆头率", "value": _percent_text(_value(stats, "headShotRatio", "headshotRate")), "note": "击杀中的爆头比例"},
            {"label": "RWS", "value": _number_text(_value(stats, "rws")), "note": "胜局贡献"},
            {"label": "MVP", "value": str(_value(stats, "mvpCount", "mvp") or "0"), "note": "局内最佳"},
            {"label": "天梯排名", "value": str(_value(stats, "pvpRank", "rank") or "-"), "note": "Ladder Rank"},
        ],
        recent_matches=[_build_pw_match_view(_dict(item)) for item in matches[:5]],
    )


def _build_pw_match_view(match: dict[str, Any]) -> dict[str, str]:
    """把一条完美平台近期比赛转换为卡片数据。"""
    explicit_result = _value(match, "isWin", "is_win")
    is_win = _flag(explicit_result) if explicit_result is not None else False
    is_tie = False
    if explicit_result is None:
        team = str(_value(match, "team", "teamId") or "")
        winner = str(_value(match, "winTeam", "winnerTeam", "win_team") or "")
        is_win = bool(team and winner and team == winner)
    score1 = _value(match, "score1", "teamScore")
    score2 = _value(match, "score2", "enemyScore")
    if score1 is not None and score2 is not None:
        is_tie = str(score1) == str(score2)
    result_text = "胜利" if is_win else ("平局" if is_tie else "失败")
    result_class = "win" if is_win else ("draw" if is_tie else "loss")
    return {
        "result_text": result_text,
        "result_class": result_class,
        "map_name": str(_value(match, "mapName", "map_name", "map") or "未知地图"),
        "score": f"{score1}:{score2}" if score1 is not None and score2 is not None else "-",
        "rating": _number_text(_value(match, "pwRating", "rating")),
        "details": "近期对局",
    }


def _build_view(
    *,
    platform: str,
    platform_name: str,
    accent: str,
    binding: PlayerBinding,
    identity_label: str,
    hero_label: str,
    hero_value: str,
    summary: list[dict[str, str]],
    metrics: list[dict[str, str]],
    recent_matches: list[dict[str, str]],
) -> dict[str, Any]:
    """组装两个平台共用的 HTML 渲染上下文。"""
    return {
        "platform": platform,
        "platform_label": platform_name,
        "accent": accent,
        "nickname": binding.player_name,
        "avatar_url": binding.avatar_url,
        "identity_label": identity_label,
        "identity": binding.domain or binding.uuid or "-",
        "hero_label": hero_label,
        "hero_value": hero_value,
        "summary": summary,
        "metrics": metrics,
        "recent_matches": recent_matches,
        "updated_at": time.strftime("%Y-%m-%d %H:%M"),
    }


async def fetch_player_stats(
    user_id: str,
    platform: str,
    nickname: str = "",
) -> dict[str, Any]:
    """查询指定昵称或当前用户绑定对象的聚合战绩。"""
    normalized = normalize_platform(platform)
    if normalized not in {"5e", "pw"}:
        raise PlayerStatsError("平台仅支持 5e 或 pw")

    query = nickname.strip()
    binding = (
        await _resolve_5e_identity(query)
        if query and normalized == "5e"
        else None
    )
    if query and normalized == "pw":
        if query.isdigit() and len(query) >= 10:
            binding = PlayerBinding("", "pw", query, uuid=query)
        else:
            binding = await _resolve_pw_identity(query)
    if binding is None:
        binding = get_binding(user_id, normalized)
    if binding is None:
        raise PlayerStatsError(
            f"未绑定{platform_label(normalized)}账号，请先使用 CS bind {normalized} <昵称>"
        )

    if normalized == "5e" and not binding.uuid:
        async with _client() as client:
            binding.uuid = await _resolve_5e_uuid(client, binding.domain)
    if normalized == "pw" and not binding.uuid:
        resolved = await _resolve_pw_identity(binding.player_name)
        binding.domain = resolved.domain
        binding.uuid = resolved.uuid
        binding.player_name = resolved.player_name
        binding.avatar_url = binding.avatar_url or resolved.avatar_url

    if binding.user_id:
        binding_store.save(binding)
    return (
        await _fetch_5e_stats(binding)
        if normalized == "5e"
        else await _fetch_pw_stats(binding)
    )
