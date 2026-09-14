import random
import urllib.parse
from pathlib import Path

import httpx

try:
    import execjs
except ImportError:  # PyExecJS 是抖音签名功能的可选依赖。
    execjs = None

header = {
    'User-Agent': "Mozilla/5.0 (Linux; Android 8.0; Pixel 2 Build/OPD3.170816.012) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Mobile Safari/537.36 Edg/87.0.664.66"
}


def generate_x_bogus_url(url, headers):
    """
            生成抖音A-Bogus签名
            :param url: 视频链接
            :return: 包含X-Bogus签名的URL
            """
    if execjs is None:
        raise RuntimeError("抖音解析需要安装 PyExecJS 及可用的 JavaScript 运行时")

    # 调用 JavaScript 函数
    query = urllib.parse.urlparse(url).query
    abogus_file_path = Path(__file__).with_name("a-bogus.js")
    with abogus_file_path.open("r", encoding="utf-8") as abogus_file:
        abogus_file_path_transcoding = abogus_file.read()
    abogus = execjs.compile(abogus_file_path_transcoding).call(
        "generate_a_bogus", query, headers["User-Agent"]
    )
    # logger.info('生成的A-Bogus签名为: {}'.format(abogus))
    return url + "&a_bogus=" + abogus


def generate_random_str(self, randomlength=16):
    """
    根据传入长度产生随机字符串
    param :randomlength
    return:random_str
    """
    random_str = ''
    base_str = 'ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789='
    length = len(base_str) - 1
    for _ in range(randomlength):
        random_str += base_str[random.randint(0, length)]
    return random_str


async def dou_transfer_other(dou_url, proxy: str | None = None):
    """
        图集临时解决方案
    :param dou_url:
    :return:
    """
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
    data = douyin_temp_data.get("data", { })
    item_id = data.get("jx", { }).get("item_id")
    item_type = data.get("jx", { }).get("type")

    if not item_id or not item_type:
        raise ValueError("备用 API 未返回 item_id 或 type")

    # 备用API成功解析图集，直接处理
    if item_type == "图集":
        item = data.get("item", { })
        cover = item.get("cover", "")
        images = item.get("images", [])
        # 只有在有图片的情况下才发送
        if images:
            author = data.get("author", { }).get("name", "")
            title = data.get("item", { }).get("title", "")
            return cover, author, title, images

    return None, None, None, None
