"""5E 与完美平台的账号绑定及聚合战绩查询。"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from .config import PLAYER_BINDINGS_PATH, PW_SESSION_PATH, config


FIVE_E_SEARCH_URL = "https://arena.5eplay.com/api/search/player/1/16"
FIVE_E_ID_URL = "https://gate.5eplay.com/userinterface/http/v1/userinterface/idTransfer"
FIVE_E_CAREER_URL = "https://gate.5eplay.com/crane/http/api/data/player_career"
FIVE_E_MATCH_URL = "https://gate.5eplay.com/crane/http/api/data/player_match"
FIVE_E_PLAYER_URL = "https://arena.5eplay.com/api/data/player"
# 完美平台旧版接口仍负责返回完整的个人统计，但必须使用当前客户端的
# 公开请求头，并将 mySteamId 设为 0；使用手机号登录得到的旧 token 已无法
# 稳定调用这两个接口。
PW_SEARCH_URL = "https://appengine.wmpvp.com/steamcn/app/search/user"
PW_CURRENT_SEARCH_URL = "https://gwapi.pwesports.cn/acty/api/v1/search"
PW_STATS_URL = "https://api.wmpvp.com/api/csgo/home/pvp/detailStats"
PW_MATCHES_URL = "https://api.wmpvp.com/api/csgo/home/match/list"
PW_LOGIN_URL = "https://passport.pwesports.cn/account/login"
PW_PUBLIC_APPVERSION = "3.7.9.203"
PW_PUBLIC_DEVICE = "rGPSR1772436611LrL5aF8eKG3"
PW_PUBLIC_TOKEN = "8e1233748353756e1d84a321753a98d599a9de48"

PLATFORM_ALIASES = {
    "5e": "5e",
    "5eplay": "5e",
    "pw": "pw",
    "wm": "pw",
    "完美": "pw",
    "完美世界": "pw",
}

SUPPORTED_PLATFORM_TEXT = "5E、5e、5eplay、wm、pw 或 完美"

# 5E 当前优先排位分段：这里使用每个分段的最高分作为边界，
# 例如 2001-2150 分归入 A-，2401 分及以上进入 S 星级。
FIVE_E_RANK_LIMITS = (
    (1200, "D"),
    (1350, "C-"),
    (1500, "C"),
    (1600, "C+"),
    (1750, "B-"),
    (1900, "B"),
    (2000, "B+"),
    (2150, "A-"),
    (2300, "A"),
    (2400, "A+"),
)

# 完美世界当前天梯分段。带“金色”的档位与同名普通档位是不同段位，
# 不能只根据字母截断；2401 分以上由 stars 决定 S 段展示。
PW_RANK_LIMITS = (
    (1000, "D"),
    (1150, "C"),
    (1300, "C+"),
    (1450, "金色 C+"),
    (1600, "B"),
    (1750, "B+"),
    (1900, "金色 B+"),
    (2050, "A"),
    (2200, "A+"),
    (2400, "金色 A+"),
)
FIVE_E_TOP_STARS_MIN = 40
FIVE_E_TOP_RANK_MAX = 100
PW_TOP_STARS_MIN = 50
PW_TOP_RANK_MAX = 999


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

    def remove(self, user_id: str, platform: str) -> PlayerBinding | None:
        """删除一个 QQ 用户的平台绑定，并返回被删除的记录。"""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_id, platform, player_name, domain, uuid, avatar_url
                FROM player_bindings
                WHERE user_id = ? AND platform = ?
                """,
                (str(user_id), platform),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                DELETE FROM player_bindings
                WHERE user_id = ? AND platform = ?
                """,
                (str(user_id), platform),
            )
            connection.commit()
        return PlayerBinding(**dict(row))


binding_store = PlayerBindingStore(PLAYER_BINDINGS_PATH)


def normalize_platform(value: str | None) -> str | None:
    """将 5E、5eplay、wm、PW、完美等输入统一为内部平台名称。"""
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


def _steam_id(value: Any) -> int | None:
    """无损解析 64 位 SteamID，避免经过 float 导致低位数字被舍入。"""
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    raw = str(value).strip()
    if not raw.isdigit():
        return None
    try:
        steam_id = int(raw, 10)
    except ValueError:
        return None
    return steam_id if steam_id > 0 else None


def _number_text(value: Any, places: int = 2) -> str:
    """把数值格式化为卡片文本。"""
    number = _float(value)
    return "-" if number is None else f"{number:.{places}f}"


def _score_text(value: Any) -> str:
    """格式化平台分数，避免把整数分数显示成 1906.0。"""
    number = _float(value)
    if number is None:
        return str(value or "-")
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _five_e_rank_text(value: Any) -> str:
    """把 5E 的数字段位标成“段”，避免卡片只显示一个无含义的数字。"""
    if value in (None, ""):
        return "-"
    raw = str(value).strip()
    if not raw:
        return "-"
    number = _float(raw)
    if number is not None and number.is_integer():
        return "-" if number <= 0 else f"{int(number)} 段"
    return raw


def _five_e_rank_from_score(score: Any, stars: Any = None) -> str:
    """按当前 5E ELO 和 S 段星数生成可读段位。"""
    score_number = _float(score)
    star_number = _int(stars)

    if score_number is not None and score_number > 2400:
        if star_number is None or star_number < 20:
            rank = "S"
        elif star_number < 40:
            rank = "SS"
        else:
            rank = "SSS"
        return f"{rank} {star_number} 星" if star_number is not None else rank

    if score_number is None or score_number <= 0:
        return "-"
    for limit, rank in FIVE_E_RANK_LIMITS:
        if score_number <= limit:
            return rank
    return "S"


def _five_e_level_info(matches: list[Any], current_mode: dict[str, Any]) -> dict[str, Any]:
    """从近期对局中取当前优先排位的段位、星数和排名信息。"""
    fallback: dict[str, Any] = {}
    for item in matches:
        match = _dict(item)
        level_info = _dict(match.get("level_info"))
        if not level_info:
            continue
        if not fallback:
            fallback = level_info
        match_type = str(_value(match, "match_type", "matchType") or "").strip()
        if match_type == "9":
            return level_info
    return fallback or current_mode


def _five_e_rank_label(score: Any, stars: Any = None, rank: Any = None) -> str:
    """生成 5E 唯一的段位显示值，Top100 达标时优先显示排名。"""
    star_number = _int(stars)
    rank_number = _int(rank)
    if (
        star_number is not None
        and star_number >= FIVE_E_TOP_STARS_MIN
        and rank_number is not None
        and 0 < rank_number <= FIVE_E_TOP_RANK_MAX
    ):
        return f"TOP{rank_number}"
    return _five_e_rank_from_score(score, stars)


def _pw_rank_from_score(score: Any, stars: Any = None, rank: Any = None) -> str:
    """按完美世界天梯分和星数生成唯一的普通/金色评级。"""
    score_number = _float(score)
    star_number = _int(stars)
    rank_number = _int(rank)

    if (
        star_number is not None
        and star_number >= PW_TOP_STARS_MIN
        and rank_number is not None
        and 0 < rank_number <= PW_TOP_RANK_MAX
    ):
        return f"TOP{rank_number}"

    if score_number is not None and score_number > 2400:
        return f"S {star_number} 星" if star_number is not None else "S"
    if score_number is None or score_number <= 0:
        return "未定级"
    for limit, rank in PW_RANK_LIMITS:
        if score_number <= limit:
            return rank
    return "S"


def _pw_rank_icon_filename(
    score: Any,
    stars: Any,
    rank: Any,
    rank_label: str,
) -> str:
    """根据完美段位、星数和排名选择本地段位图标。"""
    star_number = max(_int(stars) or 0, 0)
    rank_number = _int(rank)
    score_number = _float(score)

    if star_number >= 50:
        level = 4 if rank_number is not None and 0 < rank_number <= 999 else 3
        return f"Level_S_{level}.png"
    if (score_number is not None and score_number > 2400) or rank_label.startswith("S"):
        level = 3 if star_number >= 25 else (2 if star_number >= 10 else 1)
        return f"Level_S_{level}.png"

    filenames = {
        "D": "Level_D.svg",
        "D+": "Level_D+.svg",
        "C": "Level_C.svg",
        "C+": "Level_C+.svg",
        "金色C+": "Level_Golden_C+.svg",
        "B": "Level_B.svg",
        "B+": "Level_B+.svg",
        "金色B+": "Level_Golden_B+.svg",
        "A": "Level_A.svg",
        "A+": "Level_A+.svg",
        "金色A+": "Level_Golden_A+.svg",
    }
    return filenames.get(rank_label.replace(" ", ""), "Level_Unknown.svg")


def _pw_detail_metrics(
    stats: dict[str, Any],
    *,
    kills: int,
    deaths: int,
    assists: Any,
    kd: Any,
) -> list[dict[str, str]]:
    """从完美接口实际返回的字段中筛选可展示的详细指标。"""
    metric_values = [
        (
            "K/D",
            _number_text(kd),
            _value(stats, "kd") not in (None, "") or deaths > 0,
        ),
        (
            "K-D-A",
            f"{_integer_text(kills)} / "
            f"{_integer_text(deaths)} / "
            f"{_integer_text(assists)}",
            any(_value(stats, key) not in (None, "") for key in ("kills", "deaths", "assists")),
        ),
        ("ADR", _number_text(_value(stats, "adr"), 1), _value(stats, "adr") not in (None, "")),
        ("RWS", _number_text(_value(stats, "rws")), _value(stats, "rws") not in (None, "")),
        (
            "MVP",
            f"{_integer_text(_value(stats, 'mvpCount', 'mvp'))} 次",
            _value(stats, "mvpCount", "mvp") not in (None, ""),
        ),
        (
            "爆头率",
            _percent_text(_value(stats, "headShotRatio", "headshotRate")),
            _value(stats, "headShotRatio", "headshotRate") not in (None, ""),
        ),
        (
            "首杀率",
            _percent_text(_value(stats, "entryKillRatio", "entryRate")),
            _value(stats, "entryKillRatio", "entryRate") not in (None, ""),
        ),
        (
            "多杀",
            f"{_integer_text(_value(stats, 'multiKill'))} 次",
            _value(stats, "multiKill") not in (None, ""),
        ),
        (
            "残局胜利",
            f"{_integer_text(_value(stats, 'endingWin', 'clutchWin'))} 次",
            _value(stats, "endingWin", "clutchWin") not in (None, ""),
        ),
    ]
    highest_score = [
        number
        for item in _list(stats.get("scoreList"))
        if (number := _float(_dict(item).get("score"))) is not None
    ]
    if not highest_score:
        highest_score = [
            number
            for item in _list(stats.get("historyScores"))
            if (number := _float(item)) is not None
        ]
    if highest_score:
        metric_values.append(("近期最高分", _score_text(max(highest_score)), True))

    return [
        {"label": label, "value": value}
        for label, value, available in metric_values
        if available
    ]


def _integer_text(value: Any) -> str:
    """格式化击杀、死亡等整数统计。"""
    number = _int(value)
    return str(number) if number is not None else str(value or "-")


def _kd_text(kills: Any, deaths: Any) -> str:
    """格式化 K-D 文本。"""
    return f"{_integer_text(kills)}-{_integer_text(deaths)}"


def _ordered_match_score(
    score1: Any,
    score2: Any,
    *,
    is_win: bool = False,
    is_loss: bool = False,
    is_tie: bool = False,
) -> str:
    """把比分按玩家视角排列：胜利大分在前，失败小分在前。"""
    if score1 in (None, "") or score2 in (None, ""):
        return "-"

    left, right = str(score1), str(score2)
    try:
        left_number = float(left)
        right_number = float(right)
    except ValueError:
        return f"{left}-{right}"

    if not is_tie and ((is_win and left_number < right_number) or (is_loss and left_number > right_number)):
        left, right = right, left
    return f"{left}-{right}"


def _time_text(value: Any) -> str:
    """把平台返回的时间戳或日期文本转换为短时间。"""
    if value in (None, ""):
        return "-"

    raw = str(value).strip()
    try:
        timestamp = float(raw)
    except (TypeError, ValueError):
        return raw.replace("T", " ", 1)[:16] or "-"

    # 不同接口分别使用秒和毫秒时间戳。
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return raw[:16] or "-"


def _map_text(value: Any) -> str:
    """把平台地图代码转换为适合卡片展示的名称。"""
    raw = str(value or "").strip()
    if not raw:
        return "未知地图"
    labels = {
        "de_ancient": "Ancient",
        "de_anubis": "Anubis",
        "de_cache": "Cache",
        "de_cbble": "Cobblestone",
        "de_dust2": "Dust2",
        "de_inferno": "Inferno",
        "de_mirage": "Mirage",
        "de_nuke": "Nuke",
        "de_overpass": "Overpass",
        "de_train": "Train",
        "de_vertigo": "Vertigo",
        "cs_italy": "Italy",
        "cs_office": "Office",
    }
    return labels.get(raw.casefold(), raw)


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
            "Referer": (
                "https://arena.5eplay.com/search?keywords="
                f"{quote(nickname, safe='')}"
            ),
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
    """读取完美平台会话文件。"""
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
    steam_id = _steam_id(raw.get("steam_id") or raw.get("my_steam_id"))
    return {
        "token": token,
        "my_steam_id": steam_id or 0,
        "appversion": str(raw.get("appversion") or "3.5.4.172"),
    } if token and steam_id else {}


def _save_pw_session(token: str, steam_id: int) -> None:
    """以原子方式保存完美平台会话，避免写入过程中留下半截 JSON。"""
    path = _pw_session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="pw-session-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "token": str(token).strip(),
                    "steam_id": int(steam_id),
                    "appversion": "3.5.4.172",
                },
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
        temp_path.replace(path)
    except OSError as exc:
        raise PlayerStatsError(f"完美平台 Session 保存失败：{exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()


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

    async with _client() as client:
        payload = await _request_json(
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

    result = _dict(payload.get("result"))
    login_result = _dict(result.get("loginResult"))
    account_info = _dict(login_result.get("accountInfo"))
    token = str(_value(account_info, "token", "accessToken") or "").strip()
    steam_id = _steam_id(_value(account_info, "steamId", "steam_id", "mySteamId"))
    if not token or not steam_id:
        raise PlayerStatsError("登录成功但返回的 Session 信息不完整")

    _save_pw_session(token, steam_id)
    return account_info | {"token": token, "steamId": steam_id}


def _pw_identity_candidates(payload: dict[str, Any]) -> list[PlayerBinding]:
    """解析完美平台新旧搜索接口返回的玩家列表。"""
    users: list[Any] = []
    for item in _list(payload.get("result")):
        group = _dict(item)
        nested = _list(group.get("data"))
        users.extend(nested if nested else [group])

    candidates: list[PlayerBinding] = []
    for item in users:
        user = _dict(item)
        name = str(
            _value(
                user,
                "name",
                "pvpNickName",
                "appNickName",
                "steamNickName",
                "steamNick",
            )
            or ""
        ).strip()
        steam_id = str(
            _value(user, "steamId64Str", "steamId64", "steamId", "steam_id") or ""
        ).strip()
        if not name or not steam_id:
            continue
        candidates.append(
            PlayerBinding(
                user_id="",
                platform="pw",
                player_name=name,
                domain=str(
                    _value(user, "wanmeiId", "userId", "pvpUserId", "appNickName") or ""
                ).strip(),
                uuid=steam_id,
                avatar_url=_image_url(
                    _value(user, "avatar", "pvpAvatar", "avatarUrl", "steamAvatar")
                ),
            )
        )
    return candidates


def _pick_pw_identity(candidates: list[PlayerBinding], nickname: str) -> PlayerBinding:
    """优先选择与搜索词完全相同的完美平台昵称。"""
    nickname_key = nickname.casefold()
    return next(
        (item for item in candidates if item.player_name.casefold() == nickname_key),
        candidates[0],
    )


async def _resolve_pw_identity(nickname: str) -> PlayerBinding:
    """根据完美平台昵称解析 SteamID；公开搜索不再依赖手机号登录态。"""
    errors: list[str] = []
    async with _client() as client:
        try:
            payload = await _request_json(
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
                    str(payload.get("description") or payload.get("message") or "完美平台搜索失败")
                )
            candidates = _pw_identity_candidates(payload)
            if candidates:
                return _pick_pw_identity(candidates, nickname)
        except PlayerStatsError as exc:
            errors.append(str(exc))

        # 兼容较旧的搜索接口。它目前仍能返回昵称、SteamID、头像和 userId。
        try:
            payload = await _request_json(
                client,
                "POST",
                PW_SEARCH_URL,
                headers=_pw_public_headers(),
                json={"keyword": nickname, "page": 1},
            )
            if payload.get("code") not in (1, "1"):
                raise PlayerStatsError(
                    str(payload.get("description") or payload.get("message") or "完美平台搜索失败")
                )
            candidates = _pw_identity_candidates(payload)
            if candidates:
                return _pick_pw_identity(candidates, nickname)
        except PlayerStatsError as exc:
            errors.append(str(exc))

    if errors:
        logger.warning("完美平台玩家搜索接口失败：%s", "；".join(errors))
    raise PlayerStatsError(f"未找到完美玩家：{nickname}")


async def bind_player(user_id: str, platform: str, nickname: str) -> PlayerBinding:
    """解析并保存 5E/PW 昵称绑定。"""
    normalized = normalize_platform(platform)
    name = nickname.strip()
    if normalized is None or normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")
    if not name:
        raise PlayerStatsError("缺少玩家昵称")

    if normalized == "5e":
        binding = await _resolve_5e_identity(name)
    else:
        binding = await _resolve_pw_identity(name)
    binding.user_id = str(user_id)
    return binding_store.save(binding)


def unbind_player(user_id: str, platform: str) -> PlayerBinding | None:
    """解除当前 QQ 用户指定平台的绑定。"""
    normalized = normalize_platform(platform)
    if normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")
    return binding_store.remove(str(user_id), normalized)


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

    # 生涯接口和玩家资料接口的缓存时间可能不同；优先使用玩家资料中
    # 当前优先排位的 ELO，避免卡片把当前星段和旧的生涯分数拼在一起。
    current_mode = _dict(_dict(arena_data.get("level_info")).get("9"))
    current_elo = _float(current_mode.get("elo"))
    if current_elo is None or current_elo <= 0:
        current_level = _five_e_level_info(match_data, current_mode)
        origin_elo = _float(_value(current_level, "origin_elo", "originElo"))
        change_elo = _float(_value(current_level, "change_elo", "changeElo"))
        if origin_elo is not None and origin_elo > 0:
            current_elo = origin_elo + (change_elo or 0)
            current_mode["elo"] = current_elo
    if current_elo is not None and current_elo > 0:
        career_data["elo_9"] = current_mode["elo"]
    for source_key, target_key in (
        ("elo", "elo_9"),
        ("rating", "rating"),
        ("adr", "adr"),
        ("rws", "rws"),
    ):
        current_value = career_data.get(target_key)
        current_number = _float(current_value)
        if current_value in (None, "") or current_number == 0:
            source_value = current_mode.get(source_key)
            if source_value not in (None, ""):
                career_data[target_key] = source_value

    for source_key, target_key in (
        ("headshot", "headshot_total"),
        ("kill", "kill_total"),
        ("per_headshot", "per_headshot"),
    ):
        if target_key not in career_data and arena_data.get(source_key) not in (None, ""):
            career_data[target_key] = arena_data[source_key]

    return _build_5e_view(binding, career_data, match_data, current_mode=current_mode)


def _build_5e_view(
    binding: PlayerBinding,
    career: dict[str, Any],
    matches: list[Any],
    *,
    current_mode: dict[str, Any] | None = None,
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
    rating = _number_text(_value(career, "rating", "rating2"))
    current_mode = current_mode or {}
    current_level = _five_e_level_info(matches, current_mode)
    score_value = _value(career, "elo_9", "elo", "score", "points")
    stars = _value(current_level, "star_num", "stars", "starNum")
    top_rank = _value(current_level, "rank", "current_rank", "ranking")
    if top_rank in (None, ""):
        top_rank = _value(career, "rank")
    rank_label = _five_e_rank_label(score_value, stars, top_rank)
    rank_value = _value(
        career,
        "grade",
        "rank_name",
        "rankName",
        "level_name",
        "levelName",
        "level",
        "elo_level",
    )
    if rank_label == "-" and rank_value is None:
        rank_value = _value(current_level, "level_name", "levelName", "grade", "name")
    if rank_label == "-":
        rank_label = _five_e_rank_text(rank_value)
    score = _score_text(score_value)
    win_rate_text = _percent_text(win_rate)
    return _build_view(
        platform="5e",
        platform_name="5E",
        accent="#f47b20",
        binding=binding,
        identity_label="5E ID",
        hero_label="段位",
        hero_value=rank_label,
        summary=[
            {"label": "分数", "value": f"{score} 分"},
            {"label": "总场次", "value": str(total)},
            {"label": "综合胜率", "value": win_rate_text},
            {"label": "胜 / 平 / 负", "value": f"{wins} / {ties} / {losses}"},
        ],
        metrics=[
            {"label": "Rating", "value": rating, "note": "平台综合 Rating"},
            {"label": "ADR", "value": _number_text(_value(career, "adr"), 1), "note": "平均每回合伤害"},
            {"label": "场次（胜率）", "value": f"{total}（{win_rate_text}）", "note": "平台生涯场次"},
            {"label": "爆头率", "value": _percent_text(headshot_rate), "note": "击杀中的爆头比例"},
            {"label": "K-D", "value": _kd_text(kills, deaths), "note": f"K/D 比值 {_number_text(kd)}"},
            {"label": "KPR", "value": _number_text(kpr), "note": "场均击杀"},
            {"label": "RWS", "value": _number_text(_value(career, "rws")), "note": "胜局贡献"},
        ],
        recent_matches=[_build_5e_match_view(_dict(item)) for item in matches[:10]],
        hero_note=f"天梯分数 {score}",
    )


def _build_5e_match_view(match: dict[str, Any]) -> dict[str, str]:
    """把一条 5E 近期比赛转换为卡片数据。"""
    explicit_win = _value(match, "is_win", "isWin", "win", "won")
    explicit_tie = _value(match, "is_tie", "isTie", "tie", "draw")
    is_win = _flag(explicit_win) if explicit_win is not None else False
    is_tie = _flag(explicit_tie) if explicit_tie is not None else False
    score = _value(match, "score")
    if not score:
        score1 = _value(match, "group1_all_score", "score1")
        score2 = _value(match, "group2_all_score", "score2")
        score = _ordered_match_score(
            score1,
            score2,
            is_win=is_win and not is_tie,
            is_loss=explicit_win is not None and not is_win and not is_tie,
            is_tie=is_tie,
        )
        if explicit_win is None and explicit_tie is None and score1 is not None and score2 is not None:
            is_tie = str(score1) == str(score2)
    result_text = "胜利" if is_win else ("平局" if is_tie else "失败")
    result_class = "win" if is_win else ("draw" if is_tie else "loss")
    kills = _value(match, "kill", "kills", "killCount", "kill_count")
    deaths = _value(match, "death", "deaths", "deathCount", "death_count")
    adr = _value(match, "adr", "adpr")
    return {
        "result_text": result_text,
        "result_class": result_class,
        "time": _time_text(
            _value(
                match,
                "time",
                "match_time",
                "matchTime",
                "start_time",
                "startTime",
                "created_at",
                "createdAt",
                "date",
                "dateTime",
                "gameTime",
                "create_time",
                "createTime",
                "finish_time",
                "finishTime",
            )
        ),
        "map_name": _map_text(
            _value(match, "map", "map_name", "map_desc", "mapDesc", "mapName")
        ),
        "kd": _kd_text(kills, deaths),
        "score": str(score),
        "rating": _number_text(_value(match, "rating", "rating2", "pw_rating")),
        "adr": _number_text(adr, 1) if adr not in (None, "") else "",
    }


def _aggregate_pw_match_stats(
    binding: PlayerBinding,
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """在聚合接口不可用时，使用公开比赛列表生成一个可展示的兜底统计。"""
    total = len(matches)
    wins = 0
    ties = 0
    kills = 0
    deaths = 0
    ratings: list[float] = []
    pw_ratings: list[float] = []
    for match in matches:
        team = str(_value(match, "team", "teamId") or "")
        winner = str(_value(match, "winTeam", "winnerTeam", "win_team") or "")
        score1 = _value(match, "score1", "teamScore")
        score2 = _value(match, "score2", "enemyScore")
        if score1 is not None and score2 is not None and str(score1) == str(score2):
            ties += 1
        elif team and winner and team == winner:
            wins += 1
        kills += _int(_value(match, "kill", "kills")) or 0
        deaths += _int(_value(match, "death", "deaths")) or 0
        rating = _float(_value(match, "rating"))
        if rating is not None:
            ratings.append(rating)
        pw_rating = _float(_value(match, "pwRating", "rating"))
        if pw_rating is not None:
            pw_ratings.append(pw_rating)

    latest_score = next(
        (
            _value(match, "pvpScore", "score", "elo", "points")
            for match in matches
            if _value(match, "pvpScore", "score", "elo", "points") not in (None, "")
        ),
        None,
    )
    return {
        "name": binding.player_name,
        "steamId": binding.uuid,
        "cnt": total,
        "kills": kills,
        "deaths": deaths,
        "rating": sum(ratings) / len(ratings) if ratings else None,
        "pwRating": sum(pw_ratings) / len(pw_ratings) if pw_ratings else None,
        "pvpScore": latest_score,
        "winRate": wins / total if total else None,
    }


async def _fetch_pw_public_stats(binding: PlayerBinding, target_id: int) -> dict[str, Any]:
    """通过当前公开客户端接口读取完美平台玩家数据。"""
    headers = _pw_public_headers()
    async with _client() as client:
        stats_payload = await _request_json(
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
        stats = _dict(stats_payload.get("data"))

        try:
            recent_payload = await _request_json(
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
                    str(recent_payload.get("errorMessage") or "完美平台近期比赛获取失败")
                )
            recent_matches = [
                item
                for item in _list(_dict(recent_payload.get("data")).get("matchList"))
                if isinstance(item, dict)
            ]
        except PlayerStatsError as exc:
            if not stats:
                raise stats_error or exc
            logger.warning("完美平台近期比赛获取失败：%s", exc)
            recent_matches = []

    if not stats:
        if recent_matches:
            stats = _aggregate_pw_match_stats(binding, recent_matches)
        else:
            raise stats_error or PlayerStatsError("未找到有效的完美平台战绩数据")

    summary = {
        "nickname": str(stats.get("name") or binding.player_name),
        "avatar": _image_url(stats.get("avatar")),
        "steam_id": str(stats.get("steamId") or binding.uuid),
    }
    binding.player_name = summary["nickname"]
    binding.avatar_url = binding.avatar_url or summary["avatar"]
    return _build_pw_view(binding, stats, recent_matches)


async def _fetch_pw_stats_legacy(binding: PlayerBinding, target_id: int) -> dict[str, Any]:
    """兼容旧版手机号登录 Session 的完美平台查询。"""
    session = _load_pw_session()
    if not session:
        raise PlayerStatsError(
            "完美平台公开查询失败，请稍后重试；如需使用旧版登录态，请先使用 CS login <手机号> <验证码>"
        )

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
                    "pageSize": 10,
                    "pvpType": -1,
                    "toSteamId": target_id,
                },
            )
            recent_matches = _list(_dict(recent_payload.get("data")).get("matchList"))
        except PlayerStatsError as exc:
            logger.warning("完美平台旧版近期比赛获取失败：%s", exc)

    summary = {
        "nickname": str(stats.get("name") or binding.player_name),
        "avatar": _image_url(stats.get("avatar")),
        "steam_id": str(stats.get("steamId") or binding.uuid),
    }
    binding.player_name = summary["nickname"]
    binding.avatar_url = binding.avatar_url or summary["avatar"]
    return _build_pw_view(binding, stats, recent_matches)


async def _fetch_pw_stats(binding: PlayerBinding) -> dict[str, Any]:
    """请求完美平台聚合战绩和近期比赛。"""
    target_id = _steam_id(binding.uuid)
    if not target_id:
        raise PlayerStatsError("完美玩家 SteamID 无效")

    try:
        return await _fetch_pw_public_stats(binding, target_id)
    except PlayerStatsError as exc:
        # 公开接口变更时保留旧 Session 作为兜底，但不会把公开玩家误报成
        # “无效账号”；只有两条接口链路都失败才将错误返回给调用方。
        if not _load_pw_session():
            raise
        logger.warning("完美平台公开查询失败，尝试旧版 Session：%s", exc)
        try:
            return await _fetch_pw_stats_legacy(binding, target_id)
        except PlayerStatsError:
            raise exc


def _build_pw_view(
    binding: PlayerBinding,
    stats: dict[str, Any],
    matches: list[Any],
) -> dict[str, Any]:
    """把完美平台原始数据转换为统一卡片上下文。"""
    kills = _int(_value(stats, "kills", "kill")) or 0
    deaths = _int(_value(stats, "deaths", "death")) or 0
    assists = _value(stats, "assists", "assist")
    kd = _value(stats, "kd")
    if kd is None and deaths:
        kd = kills / deaths
    total = _int(_value(stats, "cnt", "matchCount", "totalMatch", "matches")) or 0
    wins = _int(_value(stats, "winCount", "wins", "win_total")) or 0
    ties = _int(_value(stats, "tieCount", "ties", "tie_total")) or 0
    losses = _int(_value(stats, "lossCount", "losses", "loss_total"))
    if losses is None:
        losses = max(total - wins - ties, 0)
    rating = _number_text(_value(stats, "pwRating", "rating"))
    score_value = _value(stats, "pvpScore", "score", "elo", "points")
    stars = _value(stats, "stars", "star_num", "starNum")
    ladder_rank = _value(stats, "pvpRank", "rank")
    rank_label = _pw_rank_from_score(score_value, stars, ladder_rank)
    if rank_label == "未定级":
        legacy_rank = _value(
            stats,
            "grade",
            "rankName",
            "rank_name",
            "pvpLevelName",
            "pvpRankName",
            "levelName",
            "level",
        )
        if legacy_rank not in (None, ""):
            rank_label = str(legacy_rank)
    score = _score_text(score_value)
    win_rate = _value(stats, "winRate", "win_rate")
    if win_rate is None and total:
        win_rate = wins / total
    win_rate_text = _percent_text(win_rate)
    details = _pw_detail_metrics(
        stats,
        kills=kills,
        deaths=deaths,
        assists=assists,
        kd=kd,
    )
    recent_matches = _pw_recent_match_views(stats, matches)
    view = _build_view(
        platform="pw",
        platform_name="完美世界",
        accent="#5b7cff",
        binding=binding,
        identity_label="SteamID",
        hero_label="段位",
        hero_value=rank_label,
        summary=[
            {"label": "分数", "value": f"{score} 分"},
            {"label": "总场次", "value": str(total)},
            {"label": "综合胜率", "value": win_rate_text},
            {"label": "胜 / 平 / 负", "value": f"{wins} / {ties} / {losses}"},
        ],
        metrics=[
            {"label": "PW Rating", "value": rating, "note": "完美平台 PW Rating"},
            {"label": "ADR", "value": _number_text(_value(stats, "adr"), 1), "note": "平均每回合伤害"},
            {"label": "场次（胜率）", "value": f"{total}（{win_rate_text}）", "note": "平台生涯场次"},
            {"label": "爆头率", "value": _percent_text(_value(stats, "headShotRatio", "headshotRate")), "note": "击杀中的爆头比例"},
            {"label": "K-D", "value": _kd_text(kills, deaths), "note": f"K/D 比值 {_number_text(kd)}"},
            {"label": "RWS", "value": _number_text(_value(stats, "rws")), "note": "胜局贡献"},
            {"label": "MVP", "value": str(_value(stats, "mvpCount", "mvp") or "0"), "note": "局内最佳"},
        ],
        recent_matches=recent_matches,
        hero_note=f"分数 {score}",
    )
    score_number = _float(score_value)
    view.update(
        {
            "pw_season": str(stats.get("seasonId") or "当前赛季"),
            "pw_score": score,
            "pw_rank_icon": _pw_rank_icon_filename(
                score_value,
                stars,
                ladder_rank,
                rank_label,
            ),
            "pw_stars": _integer_text(stars),
            "pw_is_s_rank": (
                (score_number is not None and score_number > 2400)
                or rank_label.startswith("S")
                or (_int(stars) or 0) >= 50
            ),
            "pw_season_matches": str(total),
            "pw_win_rate": win_rate_text,
            "pw_rating": rating,
            "pw_detail_metrics": details,
        }
    )
    return view


def _pw_recent_match_views(
    stats: dict[str, Any],
    matches: list[Any],
) -> list[dict[str, str]]:
    """转换近期比赛，并用分数历史补足接口缺失的 ELO 变化。"""
    score_changes: dict[str, int] = {}
    score_list = [_dict(item) for item in _list(stats.get("scoreList"))]
    for current, previous in zip(score_list, score_list[1:]):
        match_id = str(current.get("matchId") or "").rsplit("@", 1)[-1]
        current_score = _int(current.get("score"))
        previous_score = _int(previous.get("score"))
        if match_id and current_score is not None and previous_score is not None:
            score_changes[match_id] = current_score - previous_score

    recent: list[dict[str, str]] = []
    for item in matches[:10]:
        match = _dict(item).copy()
        match_id = str(_value(match, "matchId", "match_id") or "").rsplit("@", 1)[-1]
        score_change = _value(match, "pvpScoreChange", "pvp_score_change")
        if score_change in (None, "", 0, "0") and match_id in score_changes:
            match["pvpScoreChange"] = score_changes[match_id]
        recent.append(_build_pw_match_view(match))
    return recent


def _build_pw_match_view(match: dict[str, Any]) -> dict[str, str]:
    """把一条完美平台近期比赛转换为卡片数据。"""
    explicit_result = _value(match, "isWin", "is_win")
    is_win = _flag(explicit_result) if explicit_result is not None else False
    is_tie = False
    result_known = explicit_result is not None
    if explicit_result is None:
        team = str(_value(match, "team", "teamId") or "")
        winner = str(_value(match, "winTeam", "winnerTeam", "win_team") or "")
        is_win = bool(team and winner and team == winner)
        result_known = bool(team and winner)
    score1 = _value(match, "score1", "teamScore")
    score2 = _value(match, "score2", "enemyScore")
    if score1 is not None and score2 is not None:
        is_tie = str(score1) == str(score2)
    result_text = "胜利" if is_win else ("平局" if is_tie else "失败")
    result_class = "win" if is_win else ("draw" if is_tie else "loss")
    kills = _value(match, "kill", "kills", "killCount", "kill_count")
    deaths = _value(match, "death", "deaths", "deathCount", "death_count")
    assists = _value(match, "assist", "assists", "assistCount", "assist_count")
    score_change = _int(_value(match, "pvpScoreChange", "pvp_score_change"))
    score_change_text = (
        f"{score_change:+d}"
        if score_change not in (None, 0)
        else ("0" if score_change == 0 else "-")
    )
    score_change_class = (
        "text-green"
        if score_change is not None and score_change > 0
        else "text-red"
        if score_change is not None and score_change < 0
        else ""
    )
    adr = _value(match, "adr", "adpr")
    return {
        "result_text": result_text,
        "result_short": "胜" if is_win else ("平" if is_tie else "负"),
        "result_class": result_class,
        "time": _time_text(
            _value(
                match,
                "time",
                "matchTime",
                "match_time",
                "startTime",
                "start_time",
                "createdAt",
                "created_at",
                "date",
                "dateTime",
                "gameTime",
            )
        ),
        "map_name": _map_text(_value(match, "mapName", "map_name", "map")),
        "kd": _kd_text(kills, deaths),
        "kda": (
            f"{_integer_text(kills)} / {_integer_text(deaths)} / "
            f"{_integer_text(assists)}"
        ),
        "score": _ordered_match_score(
            score1,
            score2,
            is_win=is_win and not is_tie,
            is_loss=result_known and not is_win and not is_tie,
            is_tie=is_tie,
        ),
        "rating": _number_text(_value(match, "pwRating", "rating")),
        "we": _number_text(_value(match, "we", "WE")),
        "score_change": score_change_text,
        "score_change_class": score_change_class,
        "adr": _number_text(adr, 1) if adr not in (None, "") else "",
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
    hero_note: str = "平台生涯数据",
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
        "hero_note": hero_note,
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
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")

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
