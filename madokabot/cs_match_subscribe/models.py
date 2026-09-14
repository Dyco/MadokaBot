"""HLTV 赛事数据模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PlayerStats:
    """Rating 表中的一名选手。"""

    full_name: str
    nickname: str
    profile_url: str
    flag_url: str | None = None
    photo_url: str | None = None
    kd: str = "-"
    swing: str = "-"
    adr: str = "-"
    kast: str = "-"
    rating: str = "-"
    rating_class: str = "neutral"
    flag_src: str | None = None
    photo_src: str | None = None

    @property
    def name_before_nick(self) -> str:
        """昵称前的姓名片段，用于还原 HLTV 的 First 'nick' Last。"""
        marker = f"'{self.nickname}'"
        if self.nickname and marker in self.full_name:
            return self.full_name.split(marker, 1)[0]
        return self.full_name

    @property
    def name_after_nick(self) -> str:
        marker = f"'{self.nickname}'"
        if self.nickname and marker in self.full_name:
            return self.full_name.split(marker, 1)[1]
        return ""


@dataclass(slots=True)
class TeamStats:
    """赛事统计表中的一支队伍。"""

    name: str
    profile_url: str
    logo_url: str | None = None
    logo_src: str | None = None
    score: str | None = None
    players: list[PlayerStats] = field(default_factory=list)


@dataclass(slots=True)
class MatchData:
    """从 HLTV 比赛页面提取出的数据。"""

    match_id: str
    url: str
    event_name: str = ""
    event_url: str | None = None
    status: str = "unknown"
    status_text: str = ""
    match_time: str = ""
    match_date: str = ""
    teams: list[TeamStats] = field(default_factory=list)
    maps: list[str] = field(default_factory=list)
    has_stats: bool = False
    fetched_at: str = ""

    @property
    def is_finished(self) -> bool:
        return self.status == "finished"

    @property
    def display_title(self) -> str:
        if len(self.teams) >= 2:
            return f"{self.teams[0].name} vs {self.teams[1].name}"
        return f"HLTV Match {self.match_id}"

    def fingerprint(self) -> str:
        """生成订阅轮询用指纹，统计变化也会触发更新。"""
        payload: dict[str, Any] = {
            "status": self.status,
            "status_text": self.status_text,
            "teams": [
                {
                    "name": team.name,
                    "score": team.score,
                    "players": [
                        {
                            "nickname": player.nickname,
                            "kd": player.kd,
                            "swing": player.swing,
                            "adr": player.adr,
                            "kast": player.kast,
                            "rating": player.rating,
                        }
                        for player in team.players
                    ],
                }
                for team in self.teams
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def to_template_context(self, *, show_player_photos: bool = False) -> dict[str, Any]:
        """转换为 Jinja 模板使用的普通字典。"""
        context = asdict(self)
        for team_data, team in zip(context["teams"], self.teams):
            for player_data, player in zip(team_data["players"], team.players):
                player_data["name_before_nick"] = player.name_before_nick
                player_data["name_after_nick"] = player.name_after_nick
        context["show_player_photos"] = show_player_photos
        return context
