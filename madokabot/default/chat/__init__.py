"""聊天插件元数据与处理器加载入口。"""

from nonebot.plugin import PluginMetadata

from .config import ChatConfig
from .matchers import ASK_USAGE, CHAT_USAGE

__plugin_meta__ = PluginMetadata(
    name="Chat",
    description="使用 /ask 或 /chat 调用语言模型进行问答",
    usage=f"{ASK_USAGE}\n{CHAT_USAGE}",
    type="application",
    config=ChatConfig,
)

from . import handlers as handlers  # noqa: E402,F401
