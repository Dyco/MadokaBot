"""玩家绑定、战绩字段映射与平台业务异常。"""

from __future__ import annotations

from dataclasses import dataclass


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
