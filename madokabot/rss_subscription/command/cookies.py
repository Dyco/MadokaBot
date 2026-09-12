from nonebot.adapters.onebot.v11 import Message
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText
from nonebot_plugin_alconna import Match as AlcMatch

from .. import scheduler
from ..subscription import Rss
from .matchers import rss_cookies_cmd


@rss_cookies_cmd.handle()
async def prepare_add_cookies(matcher: Matcher, content: AlcMatch[str]) -> None:
    if content.available and len(content.result.split(maxsplit=1)) > 1:
        matcher.set_arg("COOKIES", Message(content.result))


prompt = """\
请输入：
    名称 cookies
空格分割

获取方式：
    PC端 Chrome 浏览器按 F12
    找到 network 选项卡, 
    找到对应请求点开, 复制请求中完整的 cookie
    输出的字符串就是了\
"""


@rss_cookies_cmd.got("COOKIES", prompt=prompt)
async def handle_add_cookies(rss_cookies: str = ArgPlainText("COOKIES")) -> None:
    parts = rss_cookies.strip().split(maxsplit=1)
    if len(parts) != 2:
        await rss_cookies_cmd.reject(prompt)
        return
    name, cookies = parts

    # 判断是否有该名称订阅
    rss = Rss.get_one_by_name(name=name)
    if rss is None:
        await rss_cookies_cmd.finish(f"❌ 不存在该订阅: {name}")

    rss.name = name
    rss.set_cookies(cookies)
    await scheduler.add_job(rss)
    await rss_cookies_cmd.finish(f"👏 {rss.name}的Cookies添加成功！")
