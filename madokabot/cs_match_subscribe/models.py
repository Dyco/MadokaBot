"""HLTV 赛事数据模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


# 赛事订阅的等待状态：尚未观察到第一场比赛实际进行。
EVENT_STATUS_WAITING = "waiting"
# 赛事订阅的进行状态：赛事已进入进行阶段，需要轮询比赛页面。
EVENT_STATUS_ONGOING = "ongoing"
# 赛事订阅的结束状态：赛事不再需要轮询。
EVENT_STATUS_FINISHED = "finished"
EVENT_STATUSES = {
    EVENT_STATUS_WAITING,
    EVENT_STATUS_ONGOING,
    EVENT_STATUS_FINISHED,
}


@dataclass(slots=True)
class PlayerStats:
    """Rating 表中的一名选手。"""

    full_name: str
    nickname: str
    profile_url: str
    flag_url: str | None = None
    kd: str = "-"
    swing: str = "-"
    adr: str = "-"
    kast: str = "-"
    rating: str = "-"
    rating_class: str = "neutral"
    flag_src: str | None = None

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

    @property
    def swing_class(self) -> str:
        """按 Swing 数值返回颜色类别，-1% 到 +1% 保持黑色。"""
        try:
            value = float(self.swing.rstrip("%"))
        except ValueError:
            return "neutral"
        if -1 <= value <= 1:
            return "neutral"
        return "positive" if value > 0 else "negative"


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
class EventData:
    """HLTV 赛事列表中的一项赛事。"""

    event_id: str
    name: str
    event_type: str = ""
    prize_pool: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    prize_display: str = "TBA"
    team_count: str = "-"
    location: str = ""
    flag_url: str | None = None
    flag_src: str | None = None
    banner_url: str | None = None
    banner_src: str | None = None
    date_display: str = ""
    date_display_zh: str = ""
    url: str = ""
    format_text: str = ""
    event_status: str = "unknown"

    @property
    def is_finished(self) -> bool:
        """判断 HLTV 是否已经将赛事标记为结束。"""
        return self.event_status == "finished"


@dataclass(slots=True)
class EventMatchRef:
    """赛事页面中发现的一场比赛链接。"""

    match_id: str
    url: str
    section: str = "upcoming"


@dataclass(slots=True)
class MapScore:
    """HLTV 比赛页中的单张地图比分。"""

    name: str
    team1_score: str | None = None
    team2_score: str | None = None
    started: bool = False
    finished: bool | None = None
    live: bool = False

    @property
    def is_finished(self) -> bool:
        """判断地图是否已经产生最终回合比分。"""
        if self.finished is not None:
            return self.finished
        return self.team1_score is not None and self.team2_score is not None

    @property
    def is_started(self) -> bool:
        """判断地图是否有明确的非零比分开始标记。"""
        return self.started

    @property
    def is_live(self) -> bool:
        """判断地图是否被 HLTV Scoreboard 标记为当前实时地图。"""
        return self.live

    @property
    def score_display(self) -> str:
        """返回适合推送的地图比分。"""
        return f"{self.team1_score or '-'}:{self.team2_score or '-'}"


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
    map_stats: dict[str, list[TeamStats]] = field(default_factory=dict)
    map_results: list[MapScore] = field(default_factory=list)
    format_text: str = ""
    format_code: str = ""
    round_text: str = ""
    has_stats: bool = False
    fetched_at: str = ""

    @property
    def is_finished(self) -> bool:
        return self.status == "finished"

    @property
    def has_total_rating(self) -> bool:
        """判断全图 Rating 是否已经解析出选手数据。"""
        return any(team.players for team in self.teams)

    def has_map_rating(self, map_name: str) -> bool:
        """判断指定地图 Rating 是否已经解析出选手数据。"""
        return any(team.players for team in self.map_stats.get(map_name, []))

    @property
    def rating_is_ready(self) -> bool:
        """判断即时查询或结束汇总所需的 Rating 是否齐全。"""
        finished_names: list[str] = []
        for result in self.map_results:
            if result.is_finished and result.name not in finished_names:
                finished_names.append(result.name)
        rating_names = finished_names or self.rating_map_names
        if not rating_names or not all(
            self.has_map_rating(name) for name in rating_names
        ):
            return False
        return len(rating_names) == 1 or self.has_total_rating

    @property
    def has_started(self) -> bool:
        """用 HLTV 的实时状态或系列赛比分判断比赛是否已开始。"""
        return self.status == "live" or any(
            team.score is not None for team in self.teams[:2]
        )

    @property
    def display_title(self) -> str:
        if len(self.teams) >= 2:
            return f"{self.teams[0].name} vs {self.teams[1].name}"
        return f"HLTV Match {self.match_id}"

    @property
    def rating_map_names(self) -> list[str]:
        """返回确实进行且有 Rating 数据的地图，排除未进行的 BP 地图。"""
        stats_names = set(self.map_stats)
        finished_names: list[str] = []
        for result in self.map_results:
            if (
                result.is_finished
                and result.name in stats_names
                and result.name not in finished_names
            ):
                finished_names.append(result.name)
        if any(result.is_finished for result in self.map_results):
            return finished_names

        # 某些页面结构没有地图比分节点；此时只能用已有统计区块作为回退。
        names = [name for name in self.maps if name in stats_names]
        for name in self.map_stats:
            if name not in names:
                names.append(name)
        return names

    def fingerprint(self) -> str:
        """生成订阅轮询用指纹，统计变化也会触发更新。"""
        payload: dict[str, Any] = {
            "status": self.status,
            "status_text": self.status_text,
            "format_text": self.format_text,
            "format_code": self.format_code,
            "round_text": self.round_text,
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
            "map_results": [
                {
                    "name": result.name,
                    "team1_score": result.team1_score,
                    "team2_score": result.team2_score,
                    "started": result.is_started,
                    "finished": result.is_finished,
                    "live": result.is_live,
                }
                for result in self.map_results
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def to_template_context(
        self,
        *,
        map_name: str | None = None,
    ) -> dict[str, Any]:
        """转换为 Jinja 模板使用的普通字典。"""
        context = asdict(self)
        rating_maps = self.rating_map_names
        selected_map = map_name if map_name in rating_maps else None
        selected_teams = self.map_stats.get(selected_map or "", self.teams)
        context["teams"] = [asdict(team) for team in selected_teams]
        context["maps"] = rating_maps
        context["selected_map"] = selected_map
        for team_data, team in zip(context["teams"], selected_teams):
            for player_data, player in zip(team_data["players"], team.players):
                player_data["name_before_nick"] = player.name_before_nick
                player_data["name_after_nick"] = player.name_after_nick
                player_data["swing_class"] = player.swing_class
        return context
