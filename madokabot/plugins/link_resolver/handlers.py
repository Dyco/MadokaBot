"""按原顺序加载各平台自动解析处理器。"""

# 平台 matcher 同优先级时，处理器注册顺序保持原有行为。
# isort: skip_file
from .platforms import bilibili as bilibili
from .platforms import douyin as douyin
from .platforms import tiktok as tiktok
from .platforms import acfun as acfun
from .platforms import twitter as twitter
from .platforms import xiaohongshu as xiaohongshu
from .platforms import youtube as youtube
from .platforms import netease as netease
from .platforms import kugou as kugou
from .platforms import weibo as weibo
