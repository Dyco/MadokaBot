"""加载并注册 RSS 主命令及各子命令。"""

from . import add, cookies, edit, join, matchers, remove, rsshub, show, upload

__all__ = (
    "add",
    "cookies",
    "edit",
    "join",
    "matchers",
    "remove",
    "rsshub",
    "show",
    "upload",
)
