import urllib.parse
from http.cookies import CookieError, SimpleCookie
from pathlib import Path

import httpx

try:
    import execjs
except ImportError:
    execjs = None


def build_douyin_request(
    url: str, cookie: str, referer: str
) -> tuple[str, dict[str, str]]:
    """从同一份 Cookie 提取真实设备字段，构造并签名抖音接口请求。"""
    parsed_cookie = SimpleCookie()
    try:
        parsed_cookie.load(cookie)
    except CookieError:
        raise ValueError(
            "抖音 Cookie 格式错误，请填写完整的 Cookie 请求头内容"
        ) from None
    cookies = {key: morsel.value for key, morsel in parsed_cookie.items()}
    uifid = cookies.get("UIFID") or cookies.get("UIFID_TEMP")
    if not uifid:
        raise ValueError("抖音 Cookie 缺少 UIFID/UIFID_TEMP，请重新获取完整网页 Cookie")
    fingerprint = cookies.get("s_v_web_id")
    if not fingerprint:
        raise ValueError("抖音 Cookie 缺少 s_v_web_id，请重新获取同一会话的完整 Cookie")

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
    params.update(uifid=uifid, verifyFp=fingerprint, fp=fingerprint)
    if cookies.get("msToken"):
        params["msToken"] = cookies["msToken"]
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(params)))
    return generate_x_bogus_url(url, headers), headers


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
