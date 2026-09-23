"""战绩卡片的共享格式化与视图组装。"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone, tzinfo
from typing import Any

from ..models import MatchViewFields, PlayerStatsError
from ..values import as_flag, as_float, as_int


def number_text(value: Any, places: int = 2) -> str:
    """把数值格式化为卡片文本。"""
    number = as_float(value)
    return "-" if number is None else f"{number:.{places}f}"


def nonzero_number_text(value: Any, places: int = 2) -> str:
    """将非零有限数值格式化；缺失、零或无效值统一显示横线。"""
    number = as_float(value)
    if number is None or not math.isfinite(number) or number == 0:
        return "-"
    return f"{number:.{places}f}"


def score_text(value: Any) -> str:
    """格式化平台分数，避免把整数分数显示成 1906.0。"""
    number = as_float(value)
    if number is None:
        return str(value or "-")
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def integer_text(value: Any) -> str:
    """格式化击杀、死亡等整数统计。"""
    number = as_int(value)
    return str(number) if number is not None else str(value or "-")


def kd_text(kills: Any, deaths: Any) -> str:
    """格式化 K-D 文本。"""
    return f"{integer_text(kills)}-{integer_text(deaths)}"


def ordered_match_score(
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

    if not is_tie and (
        (is_win and left_number < right_number)
        or (is_loss and left_number > right_number)
    ):
        left, right = right, left
    return f"{left}-{right}"


def time_text(value: Any, *, target_timezone: tzinfo | None = None) -> str:
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


def map_text(value: Any) -> str:
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


def percent_text(value: Any) -> str:
    """把比例或百分数统一格式化为百分比文本。"""
    number = as_float(value)
    if number is None:
        return "-"
    if number <= 1:
        number *= 100
    return f"{number:.1f}%"


def rating_class(value: Any) -> str:
    """返回 Rating 的统一颜色类。"""
    rating = as_float(value)
    if rating is None:
        return "text-neutral"
    if rating >= 1.06:
        return "text-green"
    if rating <= 0.94:
        return "text-red"
    return "text-neutral"


def build_match_view(
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
    is_win = as_flag(explicit_win) if explicit_win is not None else False
    is_tie = as_flag(explicit_tie) if explicit_tie is not None else False
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
        else ordered_match_score(
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
        f"{integer_text(kills)} / {integer_text(deaths)} / {integer_text(assists)}"
        if fields.combat_kind == "kda"
        else kd_text(kills, deaths)
    )

    rating_value = match.get(fields.rating)
    rating = number_text(rating_value)
    secondary_value = match.get(fields.secondary)
    if fields.secondary_kind == "we":
        secondary = nonzero_number_text(secondary_value)
        secondary_number = as_float(secondary_value)
        secondary_class = (
            "text-green"
            if secondary_number is not None and secondary_number >= 8
            else "text-red"
            if secondary_number not in (None, 0)
            else "text-neutral"
        )
    else:
        secondary = (
            number_text(secondary_value, 1)
            if secondary_value not in (None, "")
            else "-"
        )
        secondary_class = "text-neutral"

    score_change = as_int(match.get(fields.score_change))
    return {
        "result_text": result_text,
        "result_short": result_short,
        "result_class": result_class,
        "time": time_text(
            match.get(fields.time),
            target_timezone=target_timezone,
        ),
        "map_name": map_text(match.get(fields.map_name)),
        "score": score,
        "combat": combat,
        "rating": rating,
        "rating_class": rating_class(rating_value),
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


def build_card_view(
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
        {"unit": "", "value_class": "text-neutral", **item} for item in core_stats
    ]
    normalized_detail_metrics = [{"note": "", **item} for item in detail_metrics]
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
