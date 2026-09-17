"""5E 与完美平台的账号绑定及聚合战绩查询。"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from nonebot.log import logger

from ..madoka_bundle.config import config as madoka_config
from ..madoka_bundle.constants import SubFolder
from .assets import local_image_uri
from .config import PLAYER_BINDINGS_PATH, PW_SESSION_PATH, config
from .net import resolve_proxy


FIVE_E_SEARCH_URL = "https://arena.5eplay.com/api/search/player/1/16"
FIVE_E_ID_URL = "https://gate.5eplay.com/userinterface/http/v1/userinterface/idTransfer"
FIVE_E_MATCH_LIST_URL = "https://gate.5eplay.com/crane/http/api/data/match/list"
FIVE_E_PLAYER_HOME_URL = "https://gate.5eplay.com/crane/http/api/data/v3/player/home"
RECENT_MATCH_LIMIT = 10
FIVE_E_RETRY_ATTEMPTS = 2
FIVE_E_RETRY_DELAY = 0.5
CHINA_TIMEZONE = timezone(timedelta(hours=8))
# 完美平台旧版接口仍负责返回完整的个人统计，但必须使用当前客户端的
# 公开请求头，并将 mySteamId 设为 0；使用手机号登录得到的旧 token 已无法
# 稳定调用这两个接口。
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
FIVE_E_RANK_TIERS = (
    (1200, "D", "Level_D.avif"),
    (1350, "C-", "Level_C1.avif"),
    (1500, "C", "Level_C2.avif"),
    (1600, "C+", "Level_C3.avif"),
    (1750, "B-", "Level_B1.avif"),
    (1900, "B", "Level_B2.avif"),
    (2000, "B+", "Level_B3.avif"),
    (2150, "A-", "Level_A1.avif"),
    (2300, "A", "Level_A2.avif"),
    (2400, "A+", "Level_A3.avif"),
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


@dataclass(frozen=True, slots=True)
class MatchViewFields:
    """一个平台经过确认的近期比赛字段映射。"""

    win: str | None
    tie: str | None
    team: str | None
    winner: str | None
    direct_score: str | None
    score1: str
    score2: str
    time: str
    map_name: str
    kills: str
    deaths: str
    assists: str | None
    rating: str
    secondary: str
    score_change: str
    combat_kind: str
    secondary_kind: str


FIVE_E_MATCH_FIELDS = MatchViewFields(
    win="is_win",
    tie="is_tie",
    team=None,
    winner=None,
    direct_score="score",
    score1="group1_all_score",
    score2="group2_all_score",
    time="start_time",
    map_name="map",
    kills="kill",
    deaths="death",
    assists=None,
    rating="rating",
    secondary="adr",
    score_change="change_elo",
    combat_kind="kd",
    secondary_kind="adr",
)

PW_MATCH_FIELDS = MatchViewFields(
    win="isWin",
    tie=None,
    team="team",
    winner="winTeam",
    direct_score=None,
    score1="score1",
    score2="score2",
    time="matchTime",
    map_name="mapName",
    kills="kill",
    deaths="death",
    assists="assist",
    rating="pwRating",
    secondary="we",
    score_change="pvpScoreChange",
    combat_kind="kda",
    secondary_kind="we",
)


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


def _client() -> httpx.AsyncClient:
    """创建平台接口共用的 HTTP 客户端。"""
    return httpx.AsyncClient(
        proxy=resolve_proxy(config.hltv_proxy, madoka_config.proxy),
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
    *,
    retry_attempts: int = 0,
    retry_delay: float = 0.5,
    **kwargs: Any,
) -> dict[str, Any]:
    """请求 JSON 接口，按配置重试临时错误并统一转换为业务异常。"""
    attempts = max(0, int(retry_attempts))
    retryable_statuses = {408, 425, 429, 500, 502, 503, 504}

    for attempt in range(attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in retryable_statuses or attempt >= attempts:
                suffix = f"，已重试 {attempts} 次" if status in retryable_statuses else ""
                raise PlayerStatsError(
                    f"平台接口返回 HTTP {status}{suffix}（{method} {url}）"
                ) from exc
            logger.warning(
                "平台接口 %s %s 返回 HTTP %s，将在第 %s/%s 次重试",
                method,
                url,
                status,
                attempt + 1,
                attempts,
            )
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= attempts:
                detail = str(exc).strip() or repr(exc) or type(exc).__name__
                suffix = f"，已重试 {attempts} 次" if attempts else ""
                raise PlayerStatsError(
                    f"平台接口请求失败{suffix}（{method} {url}，"
                    f"{type(exc).__name__}）：{detail}"
                ) from exc
            logger.warning(
                "平台接口 %s %s 请求异常（%s：%s），将在第 %s/%s 次重试",
                method,
                url,
                type(exc).__name__,
                str(exc).strip() or repr(exc),
                attempt + 1,
                attempts,
            )
        else:
            if not isinstance(payload, dict):
                raise PlayerStatsError("平台接口返回格式异常")
            return payload

        await asyncio.sleep(max(0.0, retry_delay) * (attempt + 1))

    raise PlayerStatsError(f"平台接口请求失败（{method} {url}）")


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
    if number is None:
        return None
    try:
        return int(number)
    except (OverflowError, ValueError):
        return None


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


def _nonzero_number_text(value: Any, places: int = 2) -> str:
    """将非零有限数值格式化；缺失、零或无效值统一显示横线。"""
    number = _float(value)
    if number is None or not math.isfinite(number) or number == 0:
        return "-"
    return f"{number:.{places}f}"


def _score_text(value: Any) -> str:
    """格式化平台分数，避免把整数分数显示成 1906.0。"""
    number = _float(value)
    if number is None:
        return str(value or "-")
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


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
        return f"{rank} {star_number}星" if star_number is not None else rank

    if score_number is None or score_number <= 0:
        return "-"
    for limit, rank, _ in FIVE_E_RANK_TIERS:
        if score_number <= limit:
            return rank
    return "S"


def _five_e_rank_label(score: Any, stars: Any = None, rank: Any = None) -> str:
    """生成 5E 唯一的段位显示值，Top100 达标时优先显示排名。"""
    score_number = _float(score)
    star_number = _int(stars)
    rank_number = _int(rank)
    if (
        star_number is not None
        and star_number >= FIVE_E_TOP_STARS_MIN
        and rank_number is not None
        and 0 < rank_number <= FIVE_E_TOP_RANK_MAX
    ):
        return f"TOP{rank_number}"
    if score_number is None and star_number is not None and star_number > 0:
        tier = "SSS" if star_number >= 40 else "SS" if star_number >= 20 else "S"
        return f"{tier} {star_number}星"
    return _five_e_rank_from_score(score, stars)


def _five_e_rank_asset(
    score: Any,
    stars: Any = None,
    rank: Any = None,
    level_id: Any = None,
) -> tuple[str, dict[str, str] | None]:
    """根据当前 5E 分数/星数选择段位图，并返回图上的数字覆盖层。"""
    score_number = _float(score)
    star_number = _int(stars)
    rank_number = _int(rank)

    if star_number is not None and star_number >= FIVE_E_TOP_STARS_MIN:
        if rank_number is not None and 0 < rank_number <= FIVE_E_TOP_RANK_MAX:
            filename = "Level_TOP10.avif" if rank_number <= 10 else "Level_TOP100.avif"
            return filename, {"kind": "top", "text": str(rank_number)}
        return "Level_SSS.avif", {"kind": "stars", "text": str(star_number)}
    if star_number is not None and star_number >= 20:
        return "Level_SS.avif", {"kind": "stars", "text": str(star_number)}
    if star_number is not None and star_number > 0:
        return "Level_S.avif", {"kind": "stars", "text": str(star_number)}

    if score_number is not None and score_number > 0:
        for limit, _, filename in FIVE_E_RANK_TIERS:
            if score_number <= limit:
                return filename, None

    # 主页仍可能只返回 level_id；仅用已知的 S 段 ID 作为无分数时的安全回退。
    level_assets = {
        51: "Level_S.avif",
        52: "Level_SS.avif",
        53: "Level_SSS.avif",
        54: "Level_TOP10.avif",
        55: "Level_TOP100.avif",
    }
    return level_assets.get(_int(level_id), "Level_unknown.avif"), None


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
            stats.get("kd") not in (None, "") or deaths > 0,
        ),
        (
            "K-D-A",
            f"{_integer_text(kills)} / "
            f"{_integer_text(deaths)} / "
            f"{_integer_text(assists)}",
            any(stats.get(key) not in (None, "") for key in ("kills", "deaths", "assists")),
        ),
        ("ADR", _number_text(stats.get("adr"), 1), stats.get("adr") not in (None, "")),
        ("RWS", _number_text(stats.get("rws")), stats.get("rws") not in (None, "")),
        (
            "MVP",
            f"{_integer_text(stats.get('mvpCount'))} 次",
            stats.get("mvpCount") not in (None, ""),
        ),
        (
            "爆头率",
            _percent_text(stats.get("headShotRatio")),
            stats.get("headShotRatio") not in (None, ""),
        ),
        (
            "首杀率",
            _percent_text(stats.get("entryKillRatio")),
            stats.get("entryKillRatio") not in (None, ""),
        ),
        (
            "多杀",
            f"{_integer_text(stats.get('multiKill'))} 次",
            stats.get("multiKill") not in (None, ""),
        ),
        (
            "残局胜利",
            f"{_integer_text(stats.get('endingWin'))} 次",
            stats.get("endingWin") not in (None, ""),
        ),
    ]
    highest_score = [
        number
        for item in _list(stats.get("scoreList"))
        if (number := _float(_dict(item).get("score"))) is not None
        and math.isfinite(number)
        and number > 0
    ]
    recent_high_score = _score_text(max(highest_score)) if highest_score else "-"
    metric_values.append(("历史最高分", recent_high_score, True))

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


def _time_text(value: Any, *, target_timezone: tzinfo | None = None) -> str:
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
        converted = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        converted = (
            converted.astimezone(target_timezone)
            if target_timezone is not None
            else converted.astimezone()
        )
        return converted.strftime("%m-%d %H:%M")
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


def _image_url(value: Any, *, base_url: str = "") -> str:
    """规范化图片地址；仅在平台明确提供基础地址时补全相对路径。"""
    url = str(value or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url and not url.startswith(("http://", "https://", "data:")):
        return f"{base_url.rstrip('/')}/{url.lstrip('/')}" if base_url else ""
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
        retry_attempts=FIVE_E_RETRY_ATTEMPTS,
        retry_delay=FIVE_E_RETRY_DELAY,
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
        name = str(user.get("username") or "").strip()
        domain = str(user.get("domain") or "").strip()
        if name and domain:
            candidates.append(
                {
                    "name": name,
                    "domain": domain,
                    "avatar": _image_url(
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


async def _resolve_5e_uuid(
    client: httpx.AsyncClient,
    domain: str,
) -> str:
    """将 5E 玩家域名转换为战绩接口所需的 UUID。"""
    payload = await _request_json(
        client,
        "POST",
        FIVE_E_ID_URL,
        retry_attempts=FIVE_E_RETRY_ATTEMPTS,
        retry_delay=FIVE_E_RETRY_DELAY,
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
    """解析当前完美平台搜索接口返回的玩家列表。"""
    result = payload.get("result")
    if not isinstance(result, list):
        raise PlayerStatsError("完美平台搜索返回了未识别的数据结构")
    users: list[Any] = []
    for item in result:
        group = _dict(item)
        nested = group.get("data")
        if not isinstance(nested, list):
            raise PlayerStatsError("完美平台搜索结果缺少 data 列表")
        users.extend(nested)

    candidates: list[PlayerBinding] = []
    for item in users:
        user = _dict(item)
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
                avatar_url=_image_url(user.get("avatar")),
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
    async with _client() as client:
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
    payload = await _request_json(
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
        dict(item)
        for item in matches[:RECENT_MATCH_LIMIT]
        if isinstance(item, dict)
    ]


async def _fetch_5e_stats(binding: PlayerBinding) -> dict[str, Any]:
    """从 player_home 获取赛季/生涯资料，并单独读取近期逐场记录。"""
    async with _client() as client:
        home_result = await _request_json(
            client,
            "GET",
            FIVE_E_PLAYER_HOME_URL,
            retry_attempts=FIVE_E_RETRY_ATTEMPTS,
            retry_delay=FIVE_E_RETRY_DELAY,
            params={"uuid": binding.uuid},
        )
        home_data = _dict(home_result.get("data"))
        expected_sections = ("career", "season_data", "uinfo", "elo_info")
        if not home_data or any(
            key not in home_data or not isinstance(home_data[key], dict)
            for key in expected_sections
        ):
            raise PlayerStatsError("5E player_home 返回了未识别的数据结构")

        # 两个阶段按顺序执行；比赛列表连续失败时也中断本次查询，
        # 避免返回缺少近期对局的半成品卡片。
        match_data = await _fetch_5e_recent_matches(client, binding.uuid)

    return _build_5e_view(binding, home_data, match_data)


def _build_5e_view(
    binding: PlayerBinding,
    home: dict[str, Any],
    matches: list[Any],
) -> dict[str, Any]:
    """把已确认结构的 5E player_home 数据适配为唯一卡片视图。"""
    career = _dict(home.get("career"))
    season = _dict(home.get("season_data"))
    uinfo = _dict(home.get("uinfo"))
    identity_info = _dict(uinfo.get("identity"))

    total = _int(season.get("match_total")) or 0
    win_rate = season.get("per_win_match")
    rating_value = season.get("rating")
    rating = _number_text(rating_value)
    adr = season.get("adr")
    adr_text = _number_text(adr, 1)

    kills = season.get("kill")
    deaths = season.get("death")
    assists = season.get("assist")
    kd_value = season.get("kd")
    if kd_value is None:
        kill_number = _float(kills)
        death_number = _float(deaths)
        if kill_number is not None and death_number is not None and death_number > 0:
            kd_value = kill_number / death_number
    kd_text = _number_text(kd_value)

    kda_value = season.get("kda")
    if isinstance(kda_value, dict):
        kda_parts = [
            kda_value.get("kill"),
            kda_value.get("death"),
            kda_value.get("assist"),
        ]
        kda_text = " / ".join(_integer_text(part) for part in kda_parts)
    elif kda_value not in (None, ""):
        kda_text = str(kda_value)
    elif any(value not in (None, "") for value in (kills, deaths, assists)):
        kda_text = " / ".join(_integer_text(value) for value in (kills, deaths, assists))
    else:
        kda_text = "-"

    clutch_values = [
        _int(season.get(field))
        for field in ("end_1v1", "end_1v2", "end_1v3", "end_1v4", "end_1v5")
    ]
    clutch_total = (
        sum(value or 0 for value in clutch_values)
        if any(value is not None for value in clutch_values)
        else None
    )
    clutch_text = f"{clutch_total} 次" if clutch_total is not None else "-"

    # player_home 的 modes["9"] 是唯一的当前优先排位数据源。
    elo_info = _dict(home.get("elo_info"))
    modes = _dict(elo_info.get("modes"))
    current_mode = _dict(modes.get("9"))
    if not current_mode or "elo" not in current_mode:
        raise PlayerStatsError("5E player_home 缺少 elo_info.modes.9")
    current_score_number = _float(current_mode.get("elo"))
    score_value = (
        current_score_number
        if current_score_number is not None and current_score_number > 0
        else None
    )
    stars = current_mode.get("star_num")
    top_rank = current_mode.get("rank")
    rank_label = _five_e_rank_label(score_value, stars, top_rank)

    score = _integer_text(score_value)
    rank_asset, rank_overlay = _five_e_rank_asset(
        score_value,
        stars,
        top_rank,
        current_mode.get("level_id"),
    )
    win_rate_text = _percent_text(win_rate)
    best_elo = career.get("elo")

    season_name = str(season.get("season") or "").strip().upper()

    detail_metrics = [
        {"label": "KD", "value": kd_text},
        {"label": "KDA", "value": kda_text},
        {"label": "ADR", "value": adr_text},
        {"label": "RWS", "value": _number_text(season.get("rws"))},
        {
            "label": "MVP",
            "value": f"{_integer_text(season.get('mvp_total'))} 次",
        },
        {
            "label": "爆头率",
            "value": _percent_text(season.get("per_headshot")),
        },
        {
            "label": "IMPACT",
            "value": _number_text(season.get("impact")),
        },
        {
            "label": "KPR",
            "value": _number_text(season.get("kpr")),
        },
        {"label": "残局胜利", "value": clutch_text},
        {"label": "历史最高分", "value": _integer_text(best_elo)},
    ]
    username = str(uinfo.get("username") or binding.player_name)
    avatar_url = _image_url(
        uinfo.get("avatar_url") or binding.avatar_url,
        base_url="https://oss-arena.5eplay.com",
    )
    identity = identity_info.get("uid") or binding.domain or binding.uuid or "-"
    return _build_card_view(
        platform_name="5E",
        platform_brand_name="5E PLAY",
        platform_logo_src=local_image_uri(SubFolder.FIVE_E, "5ewin_logo.png"),
        nickname=username,
        avatar_url=avatar_url,
        identity_label="5E ID",
        identity=str(identity),
        season_title=f"当前赛季 · {season_name}" if season_name else "当前赛季",
        score_label="天梯分数",
        score=score,
        score_note=f"段位 {rank_label}" if rank_label != "-" else "",
        core_class="five-e",
        core_stats=[
            {
                "label": "Rating",
                "value": rating,
                "value_class": _rating_class(rating_value),
            },
            {"label": "ADR", "value": adr_text, "value_class": "text-neutral"},
            {
                "label": "赛季场次",
                "value": str(total),
                "unit": "场",
                "value_class": "text-neutral",
            },
            {"label": "胜率", "value": win_rate_text, "value_class": "text-neutral"},
        ],
        rank_icon_src=local_image_uri(SubFolder.FIVE_E, rank_asset),
        rank_icon_overlay=rank_overlay,
        detail_metrics=detail_metrics,
        recent_combat_label="KD",
        recent_rating_label="Rating",
        recent_secondary_label="ADR",
        recent_matches=[
            _build_match_view(
                _dict(item),
                FIVE_E_MATCH_FIELDS,
                target_timezone=CHINA_TIMEZONE,
            )
            for item in matches[:RECENT_MATCH_LIMIT]
            if isinstance(item, dict)
        ],
    )


def _rating_class(value: Any) -> str:
    """返回 Rating 的统一颜色类。"""
    rating = _float(value)
    if rating is None:
        return "text-neutral"
    if rating >= 1.06:
        return "text-green"
    if rating <= 0.94:
        return "text-red"
    return "text-neutral"


def _build_match_view(
    match: dict[str, Any],
    fields: MatchViewFields,
    *,
    target_timezone: tzinfo | None = None,
) -> dict[str, str]:
    """按平台字段映射生成唯一的近期比赛视图。"""
    recognized_fields = (
        fields.win,
        fields.tie,
        fields.team,
        fields.winner,
        fields.direct_score,
        fields.score1,
        fields.score2,
        fields.time,
        fields.map_name,
        fields.kills,
        fields.deaths,
        fields.assists,
        fields.rating,
        fields.secondary,
        fields.score_change,
    )
    if not any(field is not None and field in match for field in recognized_fields):
        raise PlayerStatsError("近期比赛返回了未识别的数据结构")

    explicit_win = match.get(fields.win) if fields.win else None
    explicit_tie = match.get(fields.tie) if fields.tie else None
    is_win = _flag(explicit_win) if explicit_win is not None else False
    is_tie = _flag(explicit_tie) if explicit_tie is not None else False
    result_known = explicit_win is not None or is_tie

    if not result_known and fields.team and fields.winner:
        team = str(match.get(fields.team) or "")
        winner = str(match.get(fields.winner) or "")
        if team and winner:
            is_win = team == winner
            result_known = True

    score1 = match.get(fields.score1)
    score2 = match.get(fields.score2)
    if score1 is not None and score2 is not None and str(score1) == str(score2):
        is_tie = True
        result_known = True

    if not result_known:
        result_text, result_short, result_class = "未知", "?", "unknown"
    elif is_win:
        result_text, result_short, result_class = "胜利", "胜", "win"
    elif is_tie:
        result_text, result_short, result_class = "平局", "平", "draw"
    else:
        result_text, result_short, result_class = "失败", "负", "loss"

    direct_score = match.get(fields.direct_score) if fields.direct_score else None
    score = (
        str(direct_score)
        if direct_score not in (None, "")
        else _ordered_match_score(
            score1,
            score2,
            is_win=result_known and is_win and not is_tie,
            is_loss=result_known and not is_win and not is_tie,
            is_tie=is_tie,
        )
    )
    kills = match.get(fields.kills)
    deaths = match.get(fields.deaths)
    assists = match.get(fields.assists) if fields.assists else None
    combat = (
        f"{_integer_text(kills)} / {_integer_text(deaths)} / {_integer_text(assists)}"
        if fields.combat_kind == "kda"
        else _kd_text(kills, deaths)
    )

    rating_value = match.get(fields.rating)
    rating = _number_text(rating_value)
    secondary_value = match.get(fields.secondary)
    if fields.secondary_kind == "we":
        secondary = _nonzero_number_text(secondary_value)
        secondary_number = _float(secondary_value)
        secondary_class = (
            "text-green"
            if secondary_number is not None and secondary_number >= 8
            else "text-red"
            if secondary_number not in (None, 0)
            else "text-neutral"
        )
    else:
        secondary = (
            _number_text(secondary_value, 1)
            if secondary_value not in (None, "")
            else "-"
        )
        secondary_class = "text-neutral"

    score_change = _int(match.get(fields.score_change))
    return {
        "result_text": result_text,
        "result_short": result_short,
        "result_class": result_class,
        "time": _time_text(
            match.get(fields.time),
            target_timezone=target_timezone,
        ),
        "map_name": _map_text(match.get(fields.map_name)),
        "score": score,
        "combat": combat,
        "rating": rating,
        "rating_class": _rating_class(rating_value),
        "secondary": secondary,
        "secondary_class": secondary_class,
        "score_change": "-" if score_change in (None, 0) else f"{score_change:+d}",
        "score_change_class": (
            "text-green"
            if score_change is not None and score_change > 0
            else "text-red"
            if score_change is not None and score_change < 0
            else ""
        ),
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
        team = str(match.get("team") or "")
        winner = str(match.get("winTeam") or "")
        score1 = match.get("score1")
        score2 = match.get("score2")
        if score1 is not None and score2 is not None and str(score1) == str(score2):
            ties += 1
        elif team and winner and team == winner:
            wins += 1
        kills += _int(match.get("kill")) or 0
        deaths += _int(match.get("death")) or 0
        rating = _float(match.get("rating"))
        if rating is not None:
            ratings.append(rating)
        pw_rating = _float(match.get("pwRating"))
        if pw_rating is not None:
            pw_ratings.append(pw_rating)

    latest_score = next(
        (
            match.get("pvpScore")
            for match in matches
            if match.get("pvpScore") not in (None, "")
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

    binding.player_name = str(stats.get("name") or binding.player_name)
    binding.avatar_url = binding.avatar_url or _image_url(stats.get("avatar"))
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

    binding.player_name = str(stats.get("name") or binding.player_name)
    binding.avatar_url = binding.avatar_url or _image_url(stats.get("avatar"))
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
    """把已确认结构的完美平台数据适配为唯一卡片视图。"""
    kills = _int(stats.get("kills")) or 0
    deaths = _int(stats.get("deaths")) or 0
    assists = stats.get("assists")
    kd = stats.get("kd")
    if kd is None and deaths:
        kd = kills / deaths
    total = _int(stats.get("cnt")) or 0
    wins = _int(stats.get("winCount")) or 0
    rating_value = stats.get("pwRating")
    rating = _number_text(rating_value)
    score_value = stats.get("pvpScore")
    stars = stats.get("stars")
    ladder_rank = stats.get("pvpRank")
    rank_label = _pw_rank_from_score(score_value, stars, ladder_rank)
    score = _score_text(score_value)
    win_rate = stats.get("winRate")
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
    season = str(stats.get("seasonId") or "当前赛季")
    score_number = _float(score_value)
    is_s_rank = (
        (score_number is not None and score_number > 2400)
        or rank_label.startswith("S")
        or (_int(stars) or 0) >= 50
    )
    rank_icon = _pw_rank_icon_filename(score_value, stars, ladder_rank, rank_label)
    return _build_card_view(
        platform_name="完美世界",
        platform_brand_name="完美世界电竞",
        platform_logo_src=local_image_uri(SubFolder.PERFECTWORLD, "wm_logo_big.png"),
        nickname=binding.player_name,
        avatar_url=binding.avatar_url,
        identity_label="SteamID",
        identity=binding.uuid or "-",
        season_title=f"当前赛季 · {season}" if season != "当前赛季" else "当前赛季",
        score_label="天梯分数",
        score=score,
        score_note=f"{_integer_text(stars)} 颗星" if is_s_rank else "",
        core_class="",
        core_stats=[
            {
                "label": "赛季场次",
                "value": str(total),
                "unit": "场",
                "value_class": "text-neutral",
            },
            {"label": "胜率", "value": win_rate_text, "value_class": "text-neutral"},
            {
                "label": "PW Rating",
                "value": rating,
                "value_class": _rating_class(rating_value),
            },
        ],
        rank_icon_src=local_image_uri(SubFolder.PERFECTWORLD, rank_icon),
        rank_icon_overlay=None,
        detail_metrics=details,
        recent_combat_label="K-D-A",
        recent_rating_label="PW Rating",
        recent_secondary_label="WE",
        recent_matches=recent_matches,
    )


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
    for item in matches[:RECENT_MATCH_LIMIT]:
        match = _dict(item).copy()
        match_id = str(match.get("matchId") or "").rsplit("@", 1)[-1]
        score_change = match.get("pvpScoreChange")
        if score_change in (None, "", 0, "0") and match_id in score_changes:
            match["pvpScoreChange"] = score_changes[match_id]
        recent.append(_build_match_view(match, PW_MATCH_FIELDS))
    return recent


def _build_card_view(
    *,
    platform_name: str,
    platform_brand_name: str,
    platform_logo_src: str,
    nickname: str,
    avatar_url: str,
    identity_label: str,
    identity: str,
    season_title: str,
    score_label: str,
    score: str,
    score_note: str,
    core_class: str,
    core_stats: list[dict[str, Any]],
    rank_icon_src: str,
    rank_icon_overlay: dict[str, str] | None,
    detail_metrics: list[dict[str, str]],
    recent_combat_label: str,
    recent_rating_label: str,
    recent_secondary_label: str,
    recent_matches: list[dict[str, str]],
) -> dict[str, Any]:
    """组装渲染层唯一接受的玩家战绩视图。"""
    normalized_core_stats = [
        {"unit": "", "value_class": "text-neutral", **item}
        for item in core_stats
    ]
    normalized_detail_metrics = [
        {"note": "", **item}
        for item in detail_metrics
    ]
    return {
        "platform_label": platform_name,
        "platform_brand_name": platform_brand_name,
        "platform_logo_src": platform_logo_src,
        "nickname": nickname,
        "avatar_url": avatar_url,
        "identity_label": identity_label,
        "identity": identity,
        "season_title": season_title,
        "season_caption": "本赛季数据",
        "score_label": score_label,
        "score": score,
        "score_note": score_note,
        "core_class": core_class,
        "core_stats": normalized_core_stats,
        "rank_icon_src": rank_icon_src,
        "rank_icon_overlay": rank_icon_overlay,
        "detail_metrics": normalized_detail_metrics,
        "recent_combat_label": recent_combat_label,
        "recent_rating_label": recent_rating_label,
        "recent_secondary_label": recent_secondary_label,
        "recent_matches": recent_matches,
        "updated_at": time.strftime("%Y-%m-%d %H:%M"),
    }


async def fetch_player_stats(
    user_id: str,
    platform: str,
    nickname: str = "",
) -> dict[str, Any]:
    """查询指定昵称；昵称为空时查询当前用户已经绑定的玩家。"""
    normalized = normalize_platform(platform)
    if normalized not in {"5e", "pw"}:
        raise PlayerStatsError(f"平台仅支持 {SUPPORTED_PLATFORM_TEXT}")

    query = nickname.strip()
    if query:
        binding = (
            await _resolve_5e_identity(query)
            if normalized == "5e"
            else await _resolve_pw_identity(query)
        )
    else:
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
