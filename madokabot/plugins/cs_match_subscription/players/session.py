"""完美平台登录会话的读取与原子保存。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..config import PW_SESSION_PATH, config
from .models import PlayerStatsError
from .values import parse_steam_id


def _pw_session_path() -> Path:
    """返回完美平台会话文件路径。"""
    configured = str(config.cs_pw_session_path or "").strip()
    return Path(configured) if configured else PW_SESSION_PATH


def load_pw_session() -> dict[str, Any]:
    """读取完美平台会话文件。"""
    path = _pw_session_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    token = str(raw.get("token") or "").strip()
    steam_id = parse_steam_id(raw.get("steam_id") or raw.get("my_steam_id"))
    return (
        {
            "token": token,
            "my_steam_id": steam_id or 0,
            "appversion": str(raw.get("appversion") or "3.5.4.172"),
        }
        if token and steam_id
        else {}
    )


def save_pw_session(token: str, steam_id: int) -> None:
    """以原子方式保存完美平台会话，避免写入过程中留下半截 JSON。"""
    path = _pw_session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="pw-session-",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "token": str(token).strip(),
                    "steam_id": int(steam_id),
                    "appversion": "3.5.4.172",
                },
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")
        temp_path.replace(path)
    except OSError as exc:
        raise PlayerStatsError(f"完美平台 Session 保存失败：{exc}") from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()
