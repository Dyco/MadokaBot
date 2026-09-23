"""5E 段位与战绩卡片数据适配。"""

from __future__ import annotations

from typing import Any

from madokabot.core.resources import ResourceFolder

from ...assets import local_image_uri
from ..constants import (
    CHINA_TIMEZONE,
    FIVE_E_MATCH_FIELDS,
    FIVE_E_RANK_TIERS,
    FIVE_E_TOP_RANK_MAX,
    FIVE_E_TOP_STARS_MIN,
    RECENT_MATCH_LIMIT,
)
from ..models import PlayerBinding, PlayerStatsError
from ..values import as_dict, as_float, as_int, image_url
from ..views.common import (
    build_card_view,
    build_match_view,
    integer_text,
    number_text,
    percent_text,
    rating_class,
)


def _five_e_rank_from_score(score: Any, stars: Any = None) -> str:
    """按当前 5E ELO 和 S 段星数生成可读段位。"""
    score_number = as_float(score)
    star_number = as_int(stars)

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
    score_number = as_float(score)
    star_number = as_int(stars)
    rank_number = as_int(rank)
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
    score_number = as_float(score)
    star_number = as_int(stars)
    rank_number = as_int(rank)

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
    return level_assets.get(as_int(level_id), "Level_unknown.avif"), None


def build_five_e_view(
    binding: PlayerBinding,
    home: dict[str, Any],
    matches: list[Any],
) -> dict[str, Any]:
    """把已确认结构的 5E player_home 数据适配为唯一卡片视图。"""
    career = as_dict(home.get("career"))
    season = as_dict(home.get("season_data"))
    uinfo = as_dict(home.get("uinfo"))
    identity_info = as_dict(uinfo.get("identity"))

    total = as_int(season.get("match_total")) or 0
    win_rate = season.get("per_win_match")
    rating_value = season.get("rating")
    rating = number_text(rating_value)
    adr = season.get("adr")
    adr_text = number_text(adr, 1)

    kills = season.get("kill")
    deaths = season.get("death")
    assists = season.get("assist")
    kd_value = season.get("kd")
    if kd_value is None:
        kill_number = as_float(kills)
        death_number = as_float(deaths)
        if kill_number is not None and death_number is not None and death_number > 0:
            kd_value = kill_number / death_number
    kd_text = number_text(kd_value)

    kda_value = season.get("kda")
    if isinstance(kda_value, dict):
        kda_parts = [
            kda_value.get("kill"),
            kda_value.get("death"),
            kda_value.get("assist"),
        ]
        kda_text = " / ".join(integer_text(part) for part in kda_parts)
    elif kda_value not in (None, ""):
        kda_text = str(kda_value)
    elif any(value not in (None, "") for value in (kills, deaths, assists)):
        kda_text = " / ".join(integer_text(value) for value in (kills, deaths, assists))
    else:
        kda_text = "-"

    clutch_values = [
        as_int(season.get(field))
        for field in ("end_1v1", "end_1v2", "end_1v3", "end_1v4", "end_1v5")
    ]
    clutch_total = (
        sum(value or 0 for value in clutch_values)
        if any(value is not None for value in clutch_values)
        else None
    )
    clutch_text = f"{clutch_total} 次" if clutch_total is not None else "-"

    # player_home 的 modes["9"] 是唯一的当前优先排位数据源。
    elo_info = as_dict(home.get("elo_info"))
    modes = as_dict(elo_info.get("modes"))
    current_mode = as_dict(modes.get("9"))
    if not current_mode or "elo" not in current_mode:
        raise PlayerStatsError("5E player_home 缺少 elo_info.modes.9")
    current_score_number = as_float(current_mode.get("elo"))
    score_value = (
        current_score_number
        if current_score_number is not None and current_score_number > 0
        else None
    )
    stars = current_mode.get("star_num")
    top_rank = current_mode.get("rank")
    rank_label = _five_e_rank_label(score_value, stars, top_rank)

    score = integer_text(score_value)
    rank_asset, rank_overlay = _five_e_rank_asset(
        score_value,
        stars,
        top_rank,
        current_mode.get("level_id"),
    )
    win_rate_text = percent_text(win_rate)
    best_elo = career.get("elo")

    season_name = str(season.get("season") or "").strip().upper()

    detail_metrics = [
        {"label": "KD", "value": kd_text},
        {"label": "KDA", "value": kda_text},
        {"label": "ADR", "value": adr_text},
        {"label": "RWS", "value": number_text(season.get("rws"))},
        {
            "label": "MVP",
            "value": f"{integer_text(season.get('mvp_total'))} 次",
        },
        {
            "label": "爆头率",
            "value": percent_text(season.get("per_headshot")),
        },
        {
            "label": "IMPACT",
            "value": number_text(season.get("impact")),
        },
        {
            "label": "KPR",
            "value": number_text(season.get("kpr")),
        },
        {"label": "残局胜利", "value": clutch_text},
        {"label": "历史最高分", "value": integer_text(best_elo)},
    ]
    username = str(uinfo.get("username") or binding.player_name)
    avatar_url = image_url(
        uinfo.get("avatar_url") or binding.avatar_url,
        base_url="https://oss-arena.5eplay.com",
    )
    identity = identity_info.get("uid") or binding.domain or binding.uuid or "-"
    return build_card_view(
        platform_name="5E",
        platform_brand_name="5E PLAY",
        platform_logo_src=local_image_uri(ResourceFolder.FIVE_E, "5ewin_logo.png"),
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
                "value_class": rating_class(rating_value),
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
        rank_icon_src=local_image_uri(ResourceFolder.FIVE_E, rank_asset),
        rank_icon_overlay=rank_overlay,
        detail_metrics=detail_metrics,
        recent_combat_label="KD",
        recent_rating_label="Rating",
        recent_secondary_label="ADR",
        recent_matches=[
            build_match_view(
                as_dict(item),
                FIVE_E_MATCH_FIELDS,
                target_timezone=CHINA_TIMEZONE,
            )
            for item in matches[:RECENT_MATCH_LIMIT]
            if isinstance(item, dict)
        ],
    )
