"""完美平台段位、详细指标和近期比赛视图。"""

from __future__ import annotations

import math
from typing import Any

from madokabot.core.resources import ResourceFolder

from ...assets import local_image_uri
from ..constants import (
    PW_MATCH_FIELDS,
    PW_RANK_LIMITS,
    PW_TOP_RANK_MAX,
    PW_TOP_STARS_MIN,
    RECENT_MATCH_LIMIT,
)
from ..models import PlayerBinding
from ..values import as_dict, as_float, as_int, as_list
from ..views.common import (
    build_card_view,
    build_match_view,
    integer_text,
    number_text,
    percent_text,
    rating_class,
    score_text,
)


def _pw_rank_from_score(score: Any, stars: Any = None, rank: Any = None) -> str:
    """按完美世界天梯分和星数生成唯一的普通/金色评级。"""
    score_number = as_float(score)
    star_number = as_int(stars)
    rank_number = as_int(rank)

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
    star_number = max(as_int(stars) or 0, 0)
    rank_number = as_int(rank)
    score_number = as_float(score)

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
            number_text(kd),
            stats.get("kd") not in (None, "") or deaths > 0,
        ),
        (
            "K-D-A",
            f"{integer_text(kills)} / {integer_text(deaths)} / {integer_text(assists)}",
            any(
                stats.get(key) not in (None, "")
                for key in ("kills", "deaths", "assists")
            ),
        ),
        ("ADR", number_text(stats.get("adr"), 1), stats.get("adr") not in (None, "")),
        ("RWS", number_text(stats.get("rws")), stats.get("rws") not in (None, "")),
        (
            "MVP",
            f"{integer_text(stats.get('mvpCount'))} 次",
            stats.get("mvpCount") not in (None, ""),
        ),
        (
            "爆头率",
            percent_text(stats.get("headShotRatio")),
            stats.get("headShotRatio") not in (None, ""),
        ),
        (
            "首杀率",
            percent_text(stats.get("entryKillRatio")),
            stats.get("entryKillRatio") not in (None, ""),
        ),
        (
            "多杀",
            f"{integer_text(stats.get('multiKill'))} 次",
            stats.get("multiKill") not in (None, ""),
        ),
        (
            "残局胜利",
            f"{integer_text(stats.get('endingWin'))} 次",
            stats.get("endingWin") not in (None, ""),
        ),
    ]
    highest_score = [
        number
        for item in as_list(stats.get("scoreList"))
        if (number := as_float(as_dict(item).get("score"))) is not None
        and math.isfinite(number)
        and number > 0
    ]
    recent_high_score = score_text(max(highest_score)) if highest_score else "-"
    metric_values.append(("历史最高分", recent_high_score, True))

    return [
        {"label": label, "value": value}
        for label, value, available in metric_values
        if available
    ]


def aggregate_pw_match_stats(
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
        kills += as_int(match.get("kill")) or 0
        deaths += as_int(match.get("death")) or 0
        rating = as_float(match.get("rating"))
        if rating is not None:
            ratings.append(rating)
        pw_rating = as_float(match.get("pwRating"))
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


def build_pw_view(
    binding: PlayerBinding,
    stats: dict[str, Any],
    matches: list[Any],
) -> dict[str, Any]:
    """把已确认结构的完美平台数据适配为唯一卡片视图。"""
    kills = as_int(stats.get("kills")) or 0
    deaths = as_int(stats.get("deaths")) or 0
    assists = stats.get("assists")
    kd = stats.get("kd")
    if kd is None and deaths:
        kd = kills / deaths
    total = as_int(stats.get("cnt")) or 0
    wins = as_int(stats.get("winCount")) or 0
    rating_value = stats.get("pwRating")
    rating = number_text(rating_value)
    score_value = stats.get("pvpScore")
    stars = stats.get("stars")
    ladder_rank = stats.get("pvpRank")
    rank_label = _pw_rank_from_score(score_value, stars, ladder_rank)
    score = score_text(score_value)
    win_rate = stats.get("winRate")
    if win_rate is None and total:
        win_rate = wins / total
    win_rate_text = percent_text(win_rate)
    details = _pw_detail_metrics(
        stats,
        kills=kills,
        deaths=deaths,
        assists=assists,
        kd=kd,
    )
    recent_matches = _pw_recent_match_views(stats, matches)
    season = str(stats.get("seasonId") or "当前赛季")
    score_number = as_float(score_value)
    is_s_rank = (
        (score_number is not None and score_number > 2400)
        or rank_label.startswith("S")
        or (as_int(stars) or 0) >= 50
    )
    rank_icon = _pw_rank_icon_filename(score_value, stars, ladder_rank, rank_label)
    return build_card_view(
        platform_name="完美世界",
        platform_brand_name="完美世界电竞",
        platform_logo_src=local_image_uri(
            ResourceFolder.PERFECTWORLD, "wm_logo_big.png"
        ),
        nickname=binding.player_name,
        avatar_url=binding.avatar_url,
        identity_label="SteamID",
        identity=binding.uuid or "-",
        season_title=f"当前赛季 · {season}" if season != "当前赛季" else "当前赛季",
        score_label="天梯分数",
        score=score,
        score_note=f"{integer_text(stars)} 颗星" if is_s_rank else "",
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
                "value_class": rating_class(rating_value),
            },
        ],
        rank_icon_src=local_image_uri(ResourceFolder.PERFECTWORLD, rank_icon),
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
    score_list = [as_dict(item) for item in as_list(stats.get("scoreList"))]
    for current, previous in zip(score_list, score_list[1:]):
        match_id = str(current.get("matchId") or "").rsplit("@", 1)[-1]
        current_score = as_int(current.get("score"))
        previous_score = as_int(previous.get("score"))
        if match_id and current_score is not None and previous_score is not None:
            score_changes[match_id] = current_score - previous_score

    recent: list[dict[str, str]] = []
    for item in matches[:RECENT_MATCH_LIMIT]:
        match = as_dict(item).copy()
        match_id = str(match.get("matchId") or "").rsplit("@", 1)[-1]
        score_change = match.get("pvpScoreChange")
        if score_change in (None, "", 0, "0") and match_id in score_changes:
            match["pvpScoreChange"] = score_changes[match_id]
        recent.append(build_match_view(match, PW_MATCH_FIELDS))
    return recent
