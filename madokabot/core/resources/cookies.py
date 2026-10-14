"""统一读取 Netscape 格式的 Cookie 资源。"""

from http.cookiejar import CookieJar, LoadError, MozillaCookieJar
from urllib.request import Request

from .manager import assets
from .types import ResourceType


def load_cookies(name: str) -> MozillaCookieJar:
    """以 UTF-8 读取 Cookie 资源，保留会话 Cookie 并过滤过期条目。"""
    path = assets.get_dir(ResourceType.COOKIES) / name
    jar = MozillaCookieJar(path)
    try:
        with path.open("r", encoding="utf-8") as file:
            # 标准 load 方法没有编码参数，显式打开后复用 Netscape 解析器。
            jar._really_load(file, str(path), ignore_discard=True, ignore_expires=True)
    except (LoadError, UnicodeError):
        raise ValueError(f"Cookie 资源 {name} 不是有效的 UTF-8 Netscape 文件") from None
    for cookie in jar:
        # 浏览器导出的零过期时间表示会话 Cookie。
        if cookie.expires == 0:
            cookie.expires = None
            cookie.discard = True
    jar.clear_expired_cookies()
    return jar


def get_cookie_values(jar: CookieJar, url: str) -> dict[str, str]:
    """提取适用于请求地址的 Cookie 值，按路径优先级处理同名条目。"""
    request = Request(url)
    jar.add_cookie_header(request)
    return {
        cookie.name: cookie.value
        for cookie in sorted(
            jar._cookies_for_request(request), key=lambda cookie: len(cookie.path)
        )
    }
