"""HLTV 比赛页解析器。

解析器只依赖 HTML 字符串，因此可以在不访问网络的情况下单元测试；
选择器对应 HLTV 当前页面的语义 class，而不是动态广告节点。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import MatchData, PlayerStats, TeamStats


_PLAYER_ID_RE = re.compile(r"/player/(\d+)(?:/|$)")


def _text(node: Tag | None) -> str:
    if node is None:
        return ""
    return " ".join(node.stripped_strings).strip()


def _absolute_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    return urljoin(base_url, value)


def _image_source(image: Tag | None) -> str | None:
    """读取普通、懒加载和 srcset 图片地址。"""
    if image is None:
        return None
    for attribute in (
        "src",
        "data-src",
        "data-original",
        "data-lazy-src",
        "srcset",
    ):
        value = image.get(attribute)
        if value:
            return value.split(",", 1)[0].strip().split(" ", 1)[0]
    return None


def _href_key(href: str | None) -> str | None:
    if not href:
        return None
    match = _PLAYER_ID_RE.search(href)
    if match:
        return match.group(1)
    return href.split("?", 1)[0].rstrip("/")


def _cell_text(row: Tag, selector: str, *, fallback: str = "-") -> str:
    cell = row.select_one(selector)
    value = _text(cell)
    return value or fallback


def _visible_stat(row: Tag, selector: str, *, fallback: str = "-") -> str:
    """优先选传统数据列，排除 eK-eD/eADR/eKAST 隐藏列。"""
    cell = row.select_one(f"{selector}.traditional-data")
    if cell is None:
        cells = row.select(selector)
        cell = next(
            (item for item in cells if "hidden" not in item.get("class", [])),
            None,
        )
    value = _text(cell)
    return value or fallback


def _rating_class(cell: Tag | None) -> str:
    classes = set(cell.get("class", [])) if cell else set()
    if "ratingPositive" in classes:
        return "positive"
    if "ratingNegative" in classes:
        return "negative"
    return "neutral"


def _player_photo_map(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    photos: dict[str, str] = {}
    for image in soup.select("img.player-photo"):
        link = image.find_parent("a", href=True)
        key = _href_key(link.get("href") if link else None)
        src = _absolute_url(_image_source(image), base_url)
        if key and src:
            photos.setdefault(key, src)
    return photos


def _parse_player(row: Tag, base_url: str, photo_map: dict[str, str]) -> PlayerStats | None:
    link = row.select_one("td.players a[href*='/player/']")
    if link is None:
        return None

    profile_url = _absolute_url(link.get("href"), base_url) or base_url
    key = _href_key(link.get("href"))
    name_node = link.select_one(".gtSmartphone-only.statsPlayerName")
    full_name = _text(name_node) or _text(link)
    nickname_node = row.select_one(".player-nick")
    nickname = _text(nickname_node)
    if not nickname:
        nickname = full_name
    else:
        # _text() 在 inline span 两侧会补空格；还原 HLTV 的 "First 'nick' Last"。
        full_name = re.sub(
            rf"'\s*{re.escape(nickname)}\s*'",
            lambda _: f"'{nickname}'",
            full_name,
        )

    flag = row.select_one("td.players img.flag")
    flag_url = _absolute_url(_image_source(flag), base_url)
    rating_cell = row.select_one("td.rating")
    return PlayerStats(
        full_name=full_name,
        nickname=nickname,
        profile_url=profile_url,
        flag_url=flag_url,
        photo_url=photo_map.get(key) if key else None,
        kd=_visible_stat(row, "td.kd"),
        swing=_cell_text(row, "td.roundSwing"),
        adr=_visible_stat(row, "td.adr"),
        kast=_visible_stat(row, "td.kast"),
        rating=_cell_text(row, "td.rating"),
        rating_class=_rating_class(rating_cell),
    )


def _parse_stats_tables(
    soup: BeautifulSoup,
    base_url: str,
    photo_map: dict[str, str],
) -> list[TeamStats]:
    stats_root = soup.select_one("#match-stats")
    if stats_root is None:
        return []

    tables = stats_root.select("#all-content table.totalstats")
    if not tables:
        tables = stats_root.select("table.totalstats")

    teams: list[TeamStats] = []
    for table in tables[:2]:
        header = table.select_one("tr.header-row")
        if header is None:
            continue
        team_link = header.select_one("a.teamName.team, a.teamName")
        if team_link is None:
            continue

        logo = header.select_one("td.players img.logo")
        team = TeamStats(
            name=_text(team_link),
            profile_url=_absolute_url(team_link.get("href"), base_url) or base_url,
            logo_url=_absolute_url(_image_source(logo), base_url),
        )
        for row in table.select("tbody > tr"):
            if "header-row" in row.get("class", []):
                continue
            player = _parse_player(row, base_url, photo_map)
            if player is not None:
                team.players.append(player)
        teams.append(team)
    return teams


def _parse_header_teams(
    soup: BeautifulSoup,
    base_url: str,
) -> tuple[list[TeamStats], str, str, str, str, str | None]:
    """解析赛事头部的队名、比分、时间、状态和赛事链接。"""
    match_page = soup.select_one(".match-page") or soup
    box = match_page.select_one(".teamsBox")
    if box is None:
        return [], "", "", "", "", None

    time_event = box.select_one(".timeAndEvent")
    match_time = _text(time_event.select_one(".time") if time_event else None)
    match_date = _text(time_event.select_one(".date") if time_event else None)
    countdown = _text(time_event.select_one(".countdown") if time_event else None)
    event_link = time_event.select_one(".event a") if time_event else None
    event_name = _text(event_link)
    event_url = _absolute_url(event_link.get("href") if event_link else None, base_url)

    teams: list[TeamStats] = []
    for side in ("team1", "team2"):
        gradient = box.select_one(f".{side}-gradient")
        if gradient is None:
            continue
        link = gradient.select_one("a[href*='/team/']")
        name_node = gradient.select_one(".teamName")
        logo = gradient.select_one("img.logo")
        score_node = gradient.select_one(".won, .lost, .tie")
        teams.append(
            TeamStats(
                name=_text(name_node) or _text(link),
                profile_url=_absolute_url(link.get("href") if link else None, base_url)
                or base_url,
                logo_url=_absolute_url(_image_source(logo), base_url),
                score=_text(score_node) or None,
            )
        )
    return teams, event_name, match_time, match_date, countdown, event_url


def _status_code(status_text: str, teams: list[TeamStats]) -> str:
    lowered = status_text.lower()
    if any(word in lowered for word in ("over", "finished", "complete")):
        return "finished"
    if any(word in lowered for word in ("live", "now", "in progress", "ongoing")):
        return "live"
    if any(team.score is not None for team in teams):
        return "live"
    if status_text:
        return "upcoming"
    return "unknown"


def _parse_maps(soup: BeautifulSoup) -> list[str]:
    root = soup.select_one("#match-stats")
    if root is None:
        return []
    maps: list[str] = []
    for node in root.select(".stats-menu-link > .dynamic-map-name-full"):
        value = _text(node)
        if value and value.lower() not in {"all", "all maps"} and value not in maps:
            maps.append(value)
    return maps


def parse_match_html(
    html: str,
    *,
    match_id: str,
    page_url: str,
    fetched_at: datetime | None = None,
) -> MatchData:
    """解析 HLTV match 页面并返回统一数据模型。"""
    soup = BeautifulSoup(html, "html.parser")
    header_teams, event_name, match_time, match_date, status_text, event_url = (
        _parse_header_teams(soup, page_url)
    )
    photo_map = _player_photo_map(soup, page_url)
    stats_teams = _parse_stats_tables(soup, page_url, photo_map)

    # Rating 表通常包含更可靠的队名和队标；用头部比分补回去。
    if stats_teams:
        for index, team in enumerate(stats_teams):
            if index < len(header_teams):
                team.score = header_teams[index].score
                if not team.logo_url:
                    team.logo_url = header_teams[index].logo_url
        teams = stats_teams
    else:
        teams = header_teams

    for team in teams:
        for player in team.players:
            # 兼容上游图片缺少 src、只有 data-src 的情况。
            if not player.photo_url:
                player.photo_url = photo_map.get(_href_key(player.profile_url))

    status = _status_code(status_text, teams)
    timestamp = fetched_at or datetime.now(timezone.utc)
    return MatchData(
        match_id=str(match_id),
        url=page_url,
        event_name=event_name,
        event_url=event_url,
        status=status,
        status_text=status_text,
        match_time=match_time,
        match_date=match_date,
        teams=teams,
        maps=_parse_maps(soup),
        has_stats=bool(stats_teams and any(team.players for team in stats_teams)),
        fetched_at=timestamp.isoformat(),
    )
