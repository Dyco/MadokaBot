"""加载 CS 命令处理器，先注册主命令入口。"""

# 这些导入负责注册处理器，必须保持主命令检查在前。
# isort: skip_file
from . import queries as queries
from . import settings as settings
from . import players as players
from . import subscriptions as subscriptions
from . import predictions as predictions
