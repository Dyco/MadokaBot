# Madoka 链接解析器

这是从 [`nonebot-plugin-resolver`](https://github.com/zhiyu1998/nonebot-plugin-resolver)
复制并针对 MadokaBot 独立改造的本地插件。代码不会以第三方插件形式安装或部署，
而是作为 `madokabot` 下的内置插件随项目加载。

复制基准：上游 `master` 的 `1.2.32` 代码（commit
`0df7b75735cbc0ec80920a248fd72bcf2096c675`）。

## 目录约定

- `commands.py`：主命令、帮助、权限及群级开关。
- `matchers.py`：各平台链接 matcher。
- `handlers.py`：各平台解析处理器。
- `delivery.py`、`messages.py`：Resolver 自身的视频交付和消息构造。
- `state.py`：群级开关状态的持久化。
- `core/`：下载、媒体合并、平台解析和评论渲染的核心实现。
- `constants/`：各平台请求头、接口和类型常量。
- `templates/`：评论 HTML 模板由 `core.comment` 在 LocalStore 缓存目录中维护。
- 视频、图片、音频、文章和模板临时文件统一放在 `LOCALSTORE_CACHE_DIR` 下的
  `madoka_link_resolver/`，不会写入项目根目录。

## 配置

配置沿用 NoneBot 的环境变量加载方式：

```dotenv
# 可选；留空时复用 MadokaBot 的 PROXY
RESOLVER_PROXY=""
IS_OVERSEA=false
XHS_CK=""
DOUYIN_CK=""
BILI_SESSDATA=""
R_GLOBAL_NICKNAME=""
VIDEO_DURATION_MAXIMUM=480
GLOBAL_RESOLVE_CONTROLLER=""

# MadokaBot 通用媒体配置，Resolver 与 RSS 共用
VIDEO_MESSAGE_MAX_MB=95
VIDEO_COMPRESS_MAX_MB=300
VIDEO_COMPRESS_TARGET_MB=90
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
FFMPEG_TIMEOUT=1800
GROUP_FILE_MAX_MB=2048
GROUP_FILE_UPLOAD_TIMEOUT=3600
```

`FFMPEG_TIMEOUT` 默认是 `1800` 秒。视频探测、合并或压缩超过该时间后会终止对应子进程，避免阻塞后续解析与 RSS 上传队列。

视频大小不超过 `VIDEO_MESSAGE_MAX_MB`（默认 `95` MiB）时直接发送；超过 `95` 且不超过 `VIDEO_COMPRESS_MAX_MB`（默认 `300` MiB）时压缩后发送；超过 `300` MiB 时拒绝发送。上述媒体阈值由 `madoka_bundle` 的通用配置统一提供，RSS 与 Resolver 共用。

### Bilibili 视频信息发送顺序

视频信息会合并为一条转发消息，节点顺序如下：

1. 封面图片
2. 标题与简介
3. 数据（不再请求在线观看人数）
4. 评论（开启评论时；图片模式为一个评论图片节点）
5. AI 总结（获取到时）

切换到文字评论模式后，评论会沿用逐条文字节点格式，并整体放在 AI 总结之前。

其他平台的解析说明、图片和音频也会与同一次解析的媒体内容合并转发；视频本体仍走
统一的视频消息/群文件降级流程，以兼容 LLBot 的大文件上传限制。

目前注册了 Bilibili、抖音、TikTok、ACFun、X、小红书、YouTube、网易云、酷狗
和微博链接处理器。所有链接都需要通过主命令触发，例如：

```text
解析 https://www.bilibili.com/video/BVxxxxxxxxxx
resolver https://www.youtube.com/watch?v=xxxx
解析 关闭评论
解析 开启解析
解析 帮助
```

Resolver 的全部功能只在群白名单中的群聊可用。不再需要艾特机器人；裸链接不会触发解析。端口只使用项目根目录 `.env` 中的通用
`HOST`/`PORT` 配置，链接解析器本身不提供独立端口配置。

YouTube/TikTok、抖音签名和 Bilibili 功能分别需要 `yt-dlp`、`PyExecJS`、可用的
JavaScript 运行时及 `bilibili-api-python`。这些依赖缺失时，其他插件仍可加载，
对应平台会返回明确提示。

上游许可证副本见项目根目录的
`THIRD_PARTY_LICENSES/nonebot-plugin-resolver-MulanPSL2.txt`。
