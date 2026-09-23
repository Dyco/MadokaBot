"""HLTV 赛事数据模型。"""

from __future__ import annotations

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

# 赛事比赛在赛事列表中的来源。HLTV 的 matches 页面把正在进行的比赛
# 放在 live-match-container 中，所以这里沿用 upcoming 作为“当前 live”状态；
# waiting 只表示尚未开始，finished 表示已经进入 Results。
MATCH_SECTION_UPCOMING = "upcoming"
MATCH_SECTION_WAITING = "waiting"
MATCH_SECTION_FINISHED = "finished"


def normalize_match_section(value: object) -> str:
    """规范化赛事比赛来源，并兼容旧版的 ``result`` 字段。"""
    section = str(value or "").strip().casefold()
    if section in {MATCH_SECTION_FINISHED, "result"}:
        return MATCH_SECTION_FINISHED
    if section == MATCH_SECTION_UPCOMING:
        return MATCH_SECTION_UPCOMING
    return MATCH_SECTION_WAITING


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
    section: str = MATCH_SECTION_UPCOMING
    scheduled_at: datetime | None = None


@dataclass(slots=True)
class MapScore:
    """HLTV 比赛页中的单张地图比分。"""

    name: str
    team1_score: str | None = None
    team2_score: str | None = None
    # 该字段由实时 Scoreboard 识别当前地图设置；mapholder 分数不设置它。
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
        """判断地图是否已由实时 Scoreboard 当前地图确认开始。"""
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
    scheduled_at: datetime | None = None
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
        """仅用实时 Scoreboard 当前地图判断比赛是否已开始。"""
        return any(
            result.is_started and not result.is_finished
            for result in self.map_results
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
