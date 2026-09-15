"""HLTV 比赛页解析器。

解析器只依赖 HTML 字符串，因此可以在不访问网络的情况下单元测试；
选择器对应 HLTV 当前页面的语义 class，而不是动态广告节点。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import (
    EventData,
    EventMatchRef,
    MapScore,
    MatchData,
    PlayerStats,
    TeamStats,
)

_PLAYER_ID_RE = re.compile(r"/player/(\d+)(?:/|$)")
_EVENT_ID_RE = re.compile(r"/events/(\d+)(?:/|\?|$)")
_MATCH_ID_RE = re.compile(r"/matches/(\d+)(?:/|\?|$)")
_BEST_OF_RE = re.compile(r"best\s+of\s+(\d+)", re.IGNORECASE)
_LIVE_SCORE_RE = re.compile(r"(?<!\d)(?:0\s*[-:]\s*1|1\s*[-:]\s*0)(?!\d)")


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


def _event_timestamp(node: Tag | None) -> datetime | None:
    """读取 HLTV 节点上的毫秒时间戳。"""
    if node is None:
        return None
    value = node.get("data-unix")
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _event_prize_cell(node: Tag) -> Tag | None:
    """定位赛事卡片中的奖金单元格。"""
    prize_cell = node.select_one("td.prizePoolEllipsis")
    if prize_cell is None:
        row = node.select_one(".additional-info tr:first-child, table.table tr:first-child")
        if row is not None:
            cells = row.find_all("td", recursive=False) or row.select("td")
            index = 1 if "big-event" in node.get("class", []) else 2
            prize_cell = cells[index] if len(cells) > index else None
    return prize_cell


def _event_prize_display(node: Tag) -> str:
    """读取赛事卡片展示用的奖金池文本。"""
    prize_cell = _event_prize_cell(node)
    if prize_cell is None:
        return "TBA"
    return (prize_cell.get("title") or _text(prize_cell) or "TBA").strip()


def _event_prize_pool(node: Tag) -> int | None:
    """从赛事卡片的奖金单元格中提取整数奖金池。"""
    value = _event_prize_display(node)
    digits = re.sub(r"\D", "", value)
    return int(digits) if digits else None


def _event_team_count(node: Tag) -> str:
    """读取赛事卡片中的参赛队伍数量。"""
    row = node.select_one(".additional-info tr:first-child, table.table tr:first-child")
    if row is None:
        return "-"
    cells = row.find_all("td", recursive=False) or row.select("td")
    index = 2 if "big-event" in node.get("class", []) else 1
    return _text(cells[index]) if len(cells) > index and _text(cells[index]) else "-"


def _event_date_display(date_nodes: list[Tag]) -> str:
    """组合赛事卡片中的日期展示文本。"""
    values = [_text(node) for node in date_nodes[:2] if _text(node)]
    return " - ".join(values)


def _event_date_display_zh(
    start_at: datetime | None,
    end_at: datetime | None,
) -> str:
    """将赛事日期转换为中文月份和日期格式。"""
    if start_at is None:
        return ""
    start = f"{start_at.month}月{start_at.day}日"
    if end_at is None:
        return start
    return f"{start} - {end_at.month}月{end_at.day}日"


def _parse_event(node: Tag, page_url: str) -> EventData | None:
    """解析一个 HLTV 赛事列表卡片。"""
    href = node.get("href")
    event_match = _EVENT_ID_RE.search(href or "")
    if event_match is None:
        return None

    name = _text(
        node.select_one(
            ".big-event-name, .event-col .text-ellipsis, .event-name-small .text-ellipsis"
        )
    )
    if not name:
        return None

    date_nodes = node.select("[data-unix]")
    start_at = _event_timestamp(date_nodes[0] if date_nodes else None)
    end_at = _event_timestamp(date_nodes[1] if len(date_nodes) > 1 else None)
    flag = node.select_one(".big-event-location img.flag, .smallCountry img.flag, img.flag")
    banner = node.select_one(
        ".event-holder img.event-header, .event-logo-container img.logo"
    )
    location_node = node.select_one(".big-event-location, .smallCountry .col-desc")
    location = _text(location_node).rstrip("|").strip()
    event_type = _text(node.select_one("tr:first-child td.gtSmartphone-only"))
    lowered_name = name.casefold()
    if "major" in lowered_name:
        # Major 的 Stage 赛事奖金列通常是 Other/TBA，优先按名称识别赛事级别。
        event_type = "Major"
    elif not event_type and (
        "big-event" in node.get("class", []) or "ongoing-event" in node.get(
            "class", []
        )
    ):
        # 筛选页的大型卡片没有显示赛事类型，按该页的国际赛事候选处理。
        event_type = "Intl. LAN"

    return EventData(
        event_id=event_match.group(1),
        name=name,
        event_type=event_type,
        prize_pool=_event_prize_pool(node),
        prize_display=_event_prize_display(node),
        team_count=_event_team_count(node),
        location=location,
        flag_url=_absolute_url(_image_source(flag), page_url),
        banner_url=_absolute_url(_image_source(banner), page_url),
        date_display=_event_date_display(date_nodes),
        date_display_zh=_event_date_display_zh(start_at, end_at),
        start_at=start_at,
        end_at=end_at,
        url=_absolute_url(href, page_url) or "",
    )


def _normalize_preformatted_text(node: Tag | None) -> tuple[str, str, str]:
    """整理比赛页的赛制、阶段说明和完整预格式文本。"""
    if node is None:
        return "", "", ""
    lines = [line.strip() for line in node.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "", "", ""

    first_line = lines[0]
    format_match = _BEST_OF_RE.search(first_line)
    format_code = f"BO{format_match.group(1)}" if format_match else ""
    normalized: list[str] = [first_line]
    details: list[str] = []
    for line in lines[1:]:
        if line.startswith("**"):
            line = line[2:].strip()
        elif line.startswith("*"):
            line = f"- {line[1:].strip()}"
        if line:
            normalized.append(line)
            details.append(line.lstrip("- ").strip())
    return "\n\n".join(normalized), format_code, "\n".join(details)


def _score_text(node: Tag | None) -> str | None:
    """读取数字地图比分，TBA 或空值不视为已结束。"""
    value = _text(node)
    return value if re.fullmatch(r"\d+", value) else None


def _parse_map_results(soup: BeautifulSoup) -> list[MapScore]:
    """解析比赛页中的地图名称和回合最终比分。"""
    results: list[MapScore] = []
    for holder in soup.select(".mapholder"):
        name = _text(holder.select_one(".mapname, .dynamic-map-name-full"))
        if not name:
            continue
        result = MapScore(
            name=name,
            team1_score=_score_text(
                holder.select_one(".results-left .results-team-score")
            ),
            team2_score=_score_text(
                holder.select_one(".results-right .results-team-score")
            ),
        )
        results.append(result)
    return results


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
    try:
        value = float(_text(cell))
    except ValueError:
        value = None
    if value is not None:
        if 0.95 <= value <= 1.05:
            return "neutral"
        return "positive" if value > 1.05 else "negative"
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


def _parse_stats_table(
    table: Tag,
    base_url: str,
    photo_map: dict[str, str],
) -> TeamStats | None:
    """解析一张 HLTV Rating 表。"""
    header = table.select_one("tr.header-row")
    if header is None:
        return None
    team_link = header.select_one("a.teamName.team, a.teamName")
    if team_link is None:
        return None

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
    return team


def _parse_stats_section(
    section: Tag | None,
    base_url: str,
    photo_map: dict[str, str],
) -> list[TeamStats]:
    """解析一个统计范围中的两支队伍总表。"""
    if section is None:
        return []
    teams: list[TeamStats] = []
    for table in section.select("table.totalstats")[:2]:
        team = _parse_stats_table(table, base_url, photo_map)
        if team is not None:
            teams.append(team)
    return teams


def _parse_stats_tables(
    soup: BeautifulSoup,
    base_url: str,
    photo_map: dict[str, str],
) -> tuple[list[TeamStats], dict[str, list[TeamStats]]]:
    stats_root = soup.select_one("#match-stats")
    if stats_root is None:
        return [], {}

    all_section = stats_root.select_one("#all-content")
    teams = _parse_stats_section(all_section, base_url, photo_map)
    if not teams:
        teams = _parse_stats_section(stats_root, base_url, photo_map)

    map_names_by_section: dict[str, str] = {}
    for holder in soup.select(".mapholder"):
        name = _text(holder.select_one(".mapname, .dynamic-map-name-full"))
        stats_link = holder.select_one("a[href*='/mapstatsid/']")
        match = re.search(r"/mapstatsid/(\d+)", stats_link.get("href", "") if stats_link else "")
        if name and match:
            map_names_by_section[f"{match.group(1)}-content"] = name

    fallback_names = iter(_parse_maps(soup))
    map_stats: dict[str, list[TeamStats]] = {}
    for section in stats_root.select(".stats-content[id$='-content']"):
        if section is all_section:
            continue
        map_name = map_names_by_section.get(section.get("id", ""))
        if not map_name:
            map_name = next(fallback_names, "")
        parsed = _parse_stats_section(section, base_url, photo_map)
        if map_name and parsed:
            map_stats[map_name] = parsed
    return teams, map_stats


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


def _status_code(
    status_text: str,
    teams: list[TeamStats],
    page_title: str = "",
) -> str:
    """根据倒计时、页签标题和队伍比分判断比赛状态。"""
    lowered = f"{status_text} {page_title}".lower()
    if any(word in lowered for word in ("over", "finished", "complete")):
        return "finished"
    if any(word in lowered for word in ("live", "now", "in progress", "ongoing")):
        return "live"
    if _LIVE_SCORE_RE.search(page_title):
        # 部分实时页会把 0-1/1-0 只写入浏览器页签标题。
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
    map_names = _parse_maps(soup)
    stats_teams, map_stats = _parse_stats_tables(soup, page_url, photo_map)

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

    for team in [*stats_teams, *[team for group in map_stats.values() for team in group]]:
        for player in team.players:
            # 兼容上游图片缺少 src、只有 data-src 的情况。
            if not player.photo_url:
                player.photo_url = photo_map.get(_href_key(player.profile_url))

    format_text, format_code, round_text = _normalize_preformatted_text(
        soup.select_one(".padding.preformatted-text, .preformatted-text")
    )
    page_title = _text(soup.title)
    status = _status_code(status_text, teams, page_title)
    map_results = _parse_map_results(soup)
    for result in map_results:
        if result.name not in map_names:
            map_names.append(result.name)
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
        maps=map_names,
        map_stats=map_stats,
        map_results=map_results,
        format_text=format_text,
        format_code=format_code,
        round_text=round_text,
        has_stats=bool(
            stats_teams and any(team.players for team in stats_teams)
        ) or any(team.players for group in map_stats.values() for team in group),
        fetched_at=timestamp.isoformat(),
    )


def _event_detail_prize(node: Tag | None) -> tuple[str, int | None]:
    """读取赛事详情页的奖金池。"""
    value = _text(node) or "TBA"
    digits = re.sub(r"\D", "", value)
    return value, int(digits) if digits else None


def _event_detail_formats(soup: BeautifulSoup) -> str:
    """读取赛事详情页的赛制说明。"""
    formats: list[str] = []
    for row in soup.select(".formats tr"):
        title = _text(row.select_one(".format-header"))
        description = _text(row.select_one(".format-data"))
        if title and description:
            formats.append(f"{title}：{description}")
        elif title or description:
            formats.append(title or description)
    return "\n".join(formats)


def parse_event_html(
    html: str,
    *,
    event_id: str,
    page_url: str,
) -> EventData | None:
    """解析 HLTV 赛事详情页的基础信息。"""
    soup = BeautifulSoup(html, "html.parser")
    name = _text(soup.select_one(".event-hub-title, .event-header .event-name"))
    if not name:
        return None

    date_nodes = soup.select("td.eventdate span[data-unix]")
    start_at = _event_timestamp(date_nodes[0] if date_nodes else None)
    end_at = _event_timestamp(date_nodes[1] if len(date_nodes) > 1 else None)
    prize_display, prize_pool = _event_detail_prize(
        soup.select_one("td.prizepool, .event-data td.prizepool")
    )
    location_node = soup.select_one(".location, td.location")
    flag = soup.select_one(".location img.flag, td.location img.flag, img.flag")
    banner = soup.select_one(
        ".sidebar-first-level img.event-logo, .event-logo, img.event-header"
    )
    team_count = _text(soup.select_one("td.teamsNumber")) or "-"
    lowered_name = name.casefold()
    event_type = "Major" if "major" in lowered_name else ""
    return EventData(
        event_id=str(event_id),
        name=name,
        event_type=event_type,
        prize_pool=prize_pool,
        start_at=start_at,
        end_at=end_at,
        prize_display=prize_display,
        team_count=team_count,
        location=_text(location_node),
        flag_url=_absolute_url(_image_source(flag), page_url),
        banner_url=_absolute_url(_image_source(banner), page_url),
        date_display=_event_date_display(date_nodes),
        date_display_zh=_event_date_display_zh(start_at, end_at),
        url=page_url,
        format_text=_event_detail_formats(soup),
    )


def parse_event_match_refs_html(
    html: str,
    *,
    page_url: str,
    section: str,
) -> list[EventMatchRef]:
    """解析赛事 matches/results 页面中的比赛链接。"""
    soup = BeautifulSoup(html, "html.parser")
    refs: dict[str, EventMatchRef] = {}
    for anchor in soup.select('a[href*="/matches/"]'):
        href = anchor.get("href")
        match = _MATCH_ID_RE.search(href or "")
        if match is None:
            continue
        match_id = match.group(1)
        refs.setdefault(
            match_id,
            EventMatchRef(
                match_id=match_id,
                url=_absolute_url(href, page_url) or "",
                section=section,
            ),
        )
    return list(refs.values())


def parse_events_html(
    html: str,
    *,
    page_url: str = "https://www.hltv.org/events",
) -> list[EventData]:
    """解析 HLTV 赛事列表页中的赛事卡片。"""
    soup = BeautifulSoup(html, "html.parser")
    events: dict[str, EventData] = {}
    selector = 'a[href*="/events/"]'
    for node in soup.select(selector):
        event = _parse_event(node, page_url)
        if event is None:
            continue
        previous = events.get(event.event_id)
        if previous is None or (
            previous.prize_pool is None and event.prize_pool is not None
        ):
            events[event.event_id] = event
    return list(events.values())
