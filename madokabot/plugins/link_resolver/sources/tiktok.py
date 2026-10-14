import hashlib
import time
import urllib.parse
from pathlib import Path
from urllib.request import Request

import httpx
from yarl import URL

from madokabot.core.resources import load_cookies

try:
    import execjs
except ImportError:
    execjs = None

# 抖音 Web SecSDK 项目 34 的签名盐值。
# 参考：https://github.com/Evil0ctal/Douyin_TikTok_Download_API/blob/main/src/dtk/signing/native/websign.py
DOUYIN_WEB_SIGNATURE_SALT = "A96D855A08C0A9707F8BEF0D9A527E4E"


def build_douyin_request(url: str, referer: str) -> tuple[URL, dict[str, str]]:
    """读取 Netscape Cookie 并按接口补齐签名，原样保留已签名的查询字符串。"""
    jar = load_cookies("dy_cookies.txt")
    request = Request(url)
    jar.add_cookie_header(request)
    cookie = request.get_header("Cookie", "")
    # 直接读取匹配当前域名和路径的条目，避免复杂 Cookie 值被字符串解析器丢弃。
    cookies = {
        entry.name: entry.value
        for entry in sorted(
            jar._cookies_for_request(request), key=lambda entry: len(entry.path)
        )
    }
    uifid = cookies.get("UIFID") or cookies.get("UIFID_TEMP")
    if not uifid:
        raise ValueError(
            "抖音 Cookie 资源缺少有效的 UIFID/UIFID_TEMP，请重新导出网页 Cookie"
        )
    fingerprint = cookies.get("s_v_web_id")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:118.0) "
            "Gecko/20100101 Firefox/118.0"
        ),
        "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "referer": referer,
        "cookie": cookie,
        "uifid": uifid,
    }
    parts = urllib.parse.urlsplit(url)
    params = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    params["uifid"] = uifid
    if fingerprint:
        params.update(verifyFp=fingerprint, fp=fingerprint)
    if cookies.get("msToken"):
        params["msToken"] = cookies["msToken"]
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(params)))
    url = generate_x_bogus_url(url, headers)
    if parts.path == "/aweme/v1/web/aweme/detail/":
        url, signature_headers = generate_douyin_web_signature(url, uifid)
        headers.update(signature_headers)
    return URL(url, encoded=True), headers


def generate_douyin_web_signature(url: str, uifid: str) -> tuple[str, dict[str, str]]:
    """对含 A-Bogus 的最终参数计算设备绑定的 SecSDK 签名及时间戳。"""
    parts = urllib.parse.urlsplit(url)
    timestamp = str(int(time.time()))
    params = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    params.append(("timestamp", timestamp))
    query = urllib.parse.urlencode(params, safe="*-._")
    preimage = f"{uifid}_{timestamp}_{DOUYIN_WEB_SIGNATURE_SALT}_{query}"
    signature = hashlib.md5(preimage.encode("utf-8"), usedforsecurity=False).hexdigest()
    signed_url = urllib.parse.urlunsplit(
        parts._replace(query=f"{query}&x-secsdk-web-signature={signature}")
    )
    return signed_url, {
        "x-secsdk-web-signature": signature,
        "x-secsdk-web-expire": timestamp,
    }


def generate_x_bogus_url(url: str, headers: dict[str, str]) -> str:
    """对最终查询参数和实际请求 UA 生成 A-Bogus 签名。"""
    if execjs is None:
        raise RuntimeError("抖音解析需要安装 PyExecJS 及可用的 JavaScript 运行时")

    query = urllib.parse.urlparse(url).query
    abogus_file_path = Path(__file__).with_name("a-bogus.js")
    with abogus_file_path.open("r", encoding="utf-8") as abogus_file:
        abogus_file_path_transcoding = abogus_file.read()
    try:
        abogus = execjs.compile(abogus_file_path_transcoding).call(
            "generate_a_bogus", query, headers["User-Agent"]
        )
    except execjs.Error:
        raise RuntimeError(
            "抖音 A-Bogus 签名生成失败，请检查 JavaScript 运行时和签名脚本"
        ) from None
    return url + "&" + urllib.parse.urlencode({"a_bogus": abogus})


async def dou_transfer_other(dou_url, proxy: str | None = None):
    """抖音图集获取方法。"""
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
    ) as client:
        response = await client.get(
            f"https://api.xingzhige.com/API/douyin/?url={dou_url}"
        )
        response.raise_for_status()
        douyin_temp_data = response.json()
    data = douyin_temp_data.get("data", {})
    item_id = data.get("jx", {}).get("item_id")
    item_type = data.get("jx", {}).get("type")

    if not item_id or not item_type:
        raise ValueError("备用 API 未返回 item_id 或 type")

    if item_type == "图集":
        item = data.get("item", {})
        cover = item.get("cover", "")
        images = item.get("images", [])
        if images:
            author = data.get("author", {}).get("name", "")
            title = data.get("item", {}).get("title", "")
            return cover, author, title, images

    return None, None, None, None
