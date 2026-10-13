"""赛事本地数据的读取与按周同步。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone

from nonebot import logger

from madokabot.core.storage.json_store import JsonDataStore

from .assets import sync_event_assets
from .client import HltvError, events_url, fetch_events
from .config import HLTV_EVENTS_PATH, config
from .models import EventData

_events_store = JsonDataStore(HLTV_EVENTS_PATH, {})
_sync_lock = asyncio.Lock()


def _read_catalog(source_url: str) -> tuple[datetime, list[EventData]] | None:
    """读取本地赛事库及最近成功同步时间，并还原日期字段。"""
    data = _events_store.read()
    if not isinstance(data, dict) or data.get("source_url") != source_url:
        return None
    try:
        updated_at = datetime.fromisoformat(data["updated_at"])
        events: list[EventData] = []
        for snapshot in data["events"]:
            fields = dict(snapshot)
            for key in ("start_at", "end_at"):
                fields[key] = datetime.fromisoformat(fields[key]) if fields[key] else None
            events.append(EventData(**fields))
    except (KeyError, TypeError, ValueError):
        return None
    return updated_at, events


def _write_catalog(source_url: str, events: list[EventData]) -> None:
    """按最新列表替换本地数据以完成增删更新，不限制赛事日期范围。"""
    snapshots = []
    for event in {event.event_id: event for event in events}.values():
        snapshot = asdict(event)
        for key in ("start_at", "end_at"):
            value = snapshot[key]
            snapshot[key] = value.isoformat() if value is not None else None
        snapshot["flag_src"] = None
        snapshot["banner_src"] = None
        snapshots.append(snapshot)
    _events_store.write(
        {
            "source_url": source_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "events": snapshots,
        }
    )


async def get_local_events() -> list[EventData]:
    """读取完整本地赛事库，首次查询或距上次同步满一周时同步网站。"""
    async with _sync_lock:
        source_url = events_url()
        catalog = _read_catalog(source_url)
        if catalog is not None:
            updated_at, events = catalog
            elapsed = (datetime.now(timezone.utc) - updated_at).total_seconds()
            if elapsed < config.hltv_events_cache_ttl:
                return events
        try:
            events = await fetch_events()
            await sync_event_assets(events)
        except HltvError:
            if catalog is None:
                raise
            logger.warning("HLTV 赛事数据同步失败，继续使用本地数据。")
            return catalog[1]
        _write_catalog(source_url, events)
        logger.info(f"HLTV 本地赛事库同步完成，共 {len(events)} 项赛事。")
        return events
