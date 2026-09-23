"""聊天与问答命令定义，统一遵循全局命令起始符。"""

from nonebot_plugin_alconna import Alconna, Args, on_alconna

ASK_USAGE = "/ask <问题>\n/问答 <问题>"
CHAT_USAGE = "/chat <内容>\n/聊天 <内容>"

ask_cmd = Alconna("ask", Args["question?", str])
chat_cmd = Alconna("chat", Args["question?", str])
ask_matcher = on_alconna(
    ask_cmd, use_cmd_start=True, aliases={"问答"}, priority=10, block=True
)
chat_matcher = on_alconna(
    chat_cmd, use_cmd_start=True, aliases={"聊天"}, priority=10, block=True
)
