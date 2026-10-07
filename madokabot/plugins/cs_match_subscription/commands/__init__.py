"""加载 CS 命令处理器。"""

# 主命令检查必须先于子命令处理器注册。
from . import queries as queries
from . import settings as settings
from . import players as players
from . import subscriptions as subscriptions
from . import predictions as predictions
