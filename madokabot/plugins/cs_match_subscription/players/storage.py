"""玩家平台绑定的 SQLite 存储。"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from ..config import PLAYER_BINDINGS_PATH
from .models import PlayerBinding


class PlayerBindingStore:
    """使用独立 SQLite 文件保存平台绑定，避免混入赛事订阅 JSON。"""

    def __init__(self, db_path: Path) -> None:
        """创建绑定数据库目录、连接锁和表结构。"""
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """打开绑定数据库连接。"""
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        """初始化绑定表结构。"""
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS player_bindings (
                    user_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    uuid TEXT NOT NULL DEFAULT '',
                    avatar_url TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, platform)
                )
                """
            )
            connection.commit()

    def save(self, binding: PlayerBinding) -> PlayerBinding:
        """新增或覆盖一个平台绑定。"""
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO player_bindings
                    (user_id, platform, player_name, domain, uuid, avatar_url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, platform) DO UPDATE SET
                    player_name=excluded.player_name,
                    domain=excluded.domain,
                    uuid=excluded.uuid,
                    avatar_url=excluded.avatar_url,
                    updated_at=excluded.updated_at
                """,
                (
                    binding.user_id,
                    binding.platform,
                    binding.player_name,
                    binding.domain,
                    binding.uuid,
                    binding.avatar_url,
                    int(time.time()),
                ),
            )
            connection.commit()
        return binding

    def get(self, user_id: str, platform: str) -> PlayerBinding | None:
        """读取一个 QQ 用户的平台绑定。"""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_id, platform, player_name, domain, uuid, avatar_url
                FROM player_bindings
                WHERE user_id = ? AND platform = ?
                """,
                (str(user_id), platform),
            ).fetchone()
        return PlayerBinding(**dict(row)) if row else None

    def remove(self, user_id: str, platform: str) -> PlayerBinding | None:
        """删除一个 QQ 用户的平台绑定，并返回被删除的记录。"""
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT user_id, platform, player_name, domain, uuid, avatar_url
                FROM player_bindings
                WHERE user_id = ? AND platform = ?
                """,
                (str(user_id), platform),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                DELETE FROM player_bindings
                WHERE user_id = ? AND platform = ?
                """,
                (str(user_id), platform),
            )
            connection.commit()
        return PlayerBinding(**dict(row))


binding_store = PlayerBindingStore(PLAYER_BINDINGS_PATH)
