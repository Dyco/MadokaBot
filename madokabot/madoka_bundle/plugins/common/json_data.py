# -*- coding: utf-8 -*-
"""通用 JSON 文件读写工具。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

JsonData = dict[str, Any] | list[Any]
# JSON 文件的顶层数据使用对象或数组。


class JsonDataStore:
    """负责 JSON 文件的读取、重新加载和写入。"""

    def __init__(self, save_path: Path, default: JsonData | None = None) -> None:
        """初始化 JSON 文件存储。"""
        self.save_path = Path(save_path)
        self.default = {} if default is None else default
        self.content = self.read()

    def _get_default(self) -> JsonData:
        """返回一份独立的默认数据。"""
        return deepcopy(self.default)

    def read(self) -> JsonData:
        """从磁盘读取 JSON，文件不存在或内容无效时返回默认数据。"""
        if not self.save_path.is_file():
            return self._get_default()
        try:
            data = json.loads(self.save_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._get_default()
        return data if isinstance(data, (dict, list)) else self._get_default()

    def reload(self) -> None:
        """重新从磁盘加载 JSON 数据。"""
        self.content = self.read()

    def write(self, data: JsonData | None = None) -> None:
        """以 UTF-8 编码写入 JSON 数据，并自动创建父目录。"""
        if data is not None:
            self.content = data
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(
            json.dumps(self.content, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )


__all__ = ["JsonData", "JsonDataStore"]
