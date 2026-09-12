# RSS 订阅

基于 [Quan666/ELF_RSS]适配到 MadokaBot 的 RSS 订阅插件。

## 命令

仅支持群聊，按 MadokaBot 的 `COMMAND_START`、昵称或 @ 规则使用。
```text
RSS 添加 <名称> <RSS 地址>             添加订阅（也可使用：订阅 添加）
RSS rsshub_add <路由名>               交互式添加 RSSHub 路由
RSS 删除 <名称 ...>                   取消当前群订阅/删除订阅
RSS 查看 [名称]                       查看订阅详情
RSS 查看全部 [关键词]                 查看订阅列表，关键词支持正则
RSS 修改 <名称 ...> 属性=值            修改订阅设置
RSS cookies <名称> <cookies>           设置订阅 cookies
RSS 上传文件 <磁力或 torrent 地址>     手动下载并上传群文件
RSS 选择文件 <GID> <编号>              选择多文件任务，如 1,3-5
RSS 重试 <GID>                        重试上传下载完成但上传失败的文件
RSS 删除文件 <GID>                    删除下载文件及对应任务记录
RSS 终止 <GID>                        终止下载任务（也可使用 close）
```

`RSS` 和 `订阅` 是同一个命令的两个入口；子命令也支持对应的英文名称和历史别名。

手动使用 `RSS 上传文件` 时，单文件种子会直接开始下载；多文件种子会先暂停，并以 `编号.文件名[大小]` 的格式列出文件。上传发起者在 60 秒内引用选择提示、回复 `1,2,3` 或 `1,3-5` 即可开始下载，也可以使用 `RSS 选择文件 <GID> <编号>`。磁力链接需要先获取种子元数据，因此文件列表和用于选择的实际 GID 会稍后发送。RSS 订阅自动触发的下载仍会下载全部文件，下载完成后只上传 aria2 标记为已选择的文件。

`change` 支持 RSS 的 `qq`、`qun`、`time`、`proxy`、`ot`、`op`、`ohp`、`downpic`、`downopen`、`wkey`、`bkey`、`upgroup`、`mode`、`img_num`、`stop`、`forward` 和 `rm_list` 等属性。

去重模式为 `link`、`title`、`image`，可加 `or` 使用任一条件匹配；设置为 `-1` 可关闭。`time` 可以是分钟数，也可以是五段 cron 字段（用 `_` 分隔）。

## 代码结构

- `command/`：Alconna 命令注册与交互处理。
- `subscription.py`：订阅模型、持久化和去重模式定义。
- `feed.py`、`scheduler.py`：订阅抓取与定时调度。
- `parser.py`、`handlers.py`：通用处理管线及默认处理器。
- `routes/`：Pixiv、微博、Bilibili 等站点的特化处理器。
- `cache.py`：更新判断、JSON 缓存和去重数据库。
- `content.py`、`images.py`：正文与媒体内容处理。
- `download.py`、`delivery.py`：下载后端及消息投递。
- `utils.py`：代理、Bot 查询、目标校验等通用辅助函数。

## MadokaBot 配置适配

- 网络请求统一优先使用 MadokaBot 的 `PROXY`；订阅的 `proxy=1` 表示该订阅启用此代理。
- 订阅、订阅缓存和去重数据库统一存放在 LocalStore 的 `madokabot_rss_subscription` 数据目录中。当前 `.env.prod` 的 `LOCALSTORE_DATA_DIR` 为 `./assets/data`，因此默认目录是 `assets/data/madokabot_rss_subscription/`。
- `SUPERUSERS`、`NICKNAME` 直接使用 NoneBot/MadokaBot 的通用配置。
- 原 ELF_RSS 的 `RSS_PROXY` 仍可作为没有 `PROXY` 时的兼容回退，但新部署应只配置 `PROXY`。
- `FIRST_BOOT_MESSAGE` 和 `BOOT_SUCCESS_MESSAGE` 可分别修改首次启动、启动成功时发送的提示文本。

图片下载/压缩、Pixiv/微博/Bilibili/Twitter/Danbooru/Yande.re/YouTube 特殊解析、aria2 种子下载上传、消息转发和多目标订阅均保留原功能；RSS 内容直接按原文展示，不再调用翻译服务。aria2 由 MadokaBot 通过 JSON-RPC 控制，Python 依赖已经包含在项目环境中，但 `aria2c` 程序需要在服务器上单独安装并运行。

## Danbooru 配置

Danbooru 订阅会把 `/posts.atom` 和 `/posts.json` 地址统一转换为官方 `/posts.json` API 请求，并保留原地址中的 `limit`、`tags` 等查询参数。程序直接使用 API 返回的作品页、发布时间、评分、标签以及预览/大图地址，不再抓取作品 HTML 页面。

公开作品无需登录即可读取。按照 Danbooru API 的客户端标识建议，可以配置自己的 Danbooru 用户 ID；需要访问账户可见内容时，再同时配置用户名和 API Key：

```ini
DANBOORU_USER_ID=123456
DANBOORU_LOGIN="your_name"
DANBOORU_API_KEY="your_api_key"
```

用户名和 API Key 必须同时配置，API Key 应当只保存在环境配置中。已有的 Danbooru Atom 订阅不需要删除重建；部署新代码并重新启用订阅后会自动改走 JSON API。

## aria2 配置（Linux）

Debian/Ubuntu 可以安装 aria2：

```bash
sudo apt update
sudo apt install aria2
```

启动 aria2 RPC 示例（仓库中也提供了 `aria2.conf.example`）：

```bash
aria2c \\
  --enable-rpc=true \\
  --rpc-listen-all=false \\
  --rpc-listen-port=6800 \\
  --rpc-secret=change-this-secret \\
  --dir=/srv/madoka/downloads \\
  --continue=true
```

建议使用 systemd 或 Docker 保持 aria2c 常驻运行。`aria2c` 的下载目录必须与 `ARIA2_DOWNLOAD_PATH` 相同，并且运行 MadokaBot 的用户需要有读取权限，aria2 运行用户需要有写入权限。

对应 `.env.prod` 配置：

```ini
ARIA2_RPC_URL="http://127.0.0.1:6800/jsonrpc"
ARIA2_RPC_SECRET="change-this-secret"
ARIA2_DOWNLOAD_PATH="/srv/madoka/downloads"
ARIA2_ACQUIRE_TIMEOUT=60
ARIA2_FILE_CLEANUP_DELAY=3600
ARIA2_MAX_FILE_SIZE_MB=2048
ARIA2_MAX_TOTAL_SIZE_MB=4096
DOWN_STATUS_MSG_GROUP="[]"
DOWN_STATUS_MSG_DATE=300
DOWN_STATUS_MSG_RECALL_DELAY=110
```

订阅开启 `downopen=1` 后，RSS 中的磁力链接或 `.torrent` 链接会提交给 aria2。机器人提交的任务会设置 `seed-time=0`，下载完成后不继续做种。`ARIA2_ACQUIRE_TIMEOUT` 控制 torrent 链接、aria2 RPC 初始信息及磁力元数据的获取时限，单位为秒，默认是 `60`；获取失败或超时后会放弃任务，进入正式文件下载后不再受该时限影响。`ARIA2_FILE_CLEANUP_DELAY` 控制上传处理结束后的文件保留时间，单位为秒，默认是 `3600`；设为 `0` 可以关闭自动清理。`ARIA2_MAX_FILE_SIZE_MB` 限制单个文件大小，默认是 `2048` MiB；`ARIA2_MAX_TOTAL_SIZE_MB` 限制单个 aria2 下载任务的总大小，默认是 `4096` MiB。任一限制超出时都会拒绝整个下载任务。`DOWN_STATUS_MSG_DATE` 控制下载进度检查及提示间隔，单位为秒，默认是 `300`；`DOWN_STATUS_MSG_RECALL_DELAY` 控制每条进度消息独立撤回的延迟，默认是 `110` 秒，设为 `0` 时不自动撤回。下载完成后，插件会通过 OneBot 的 `upload_group_file` 上传文件到该订阅的群组。上传失败时会发送包含 GID 的提醒，并暂停自动清理；确认群文件中没有同名文件后，可以使用 `RSS 重试 <GID>` 重试当前群的失败文件。全部上传成功后才会重新开始文件清理倒计时。不再需要失败文件时，可以使用 `RSS 删除文件 <GID>` 立即删除该任务的下载文件、上传失败记录和 aria2 任务记录。若 aria2 和 MadokaBot 使用 Docker，两个容器必须挂载同一个下载目录，并使用相同的容器内路径；此时 `ARIA2_RPC_URL` 应填写 aria2 服务名（例如 `http://aria2:6800/jsonrpc`），不能填写指向 MadokaBot 容器自身的 `127.0.0.1`。

使用 `RSS 终止 <GID>` 或 `RSS close <GID>` 可以停止尚未完成的 aria2 任务，同时停止机器人对该任务的进度检查。该命令不会删除已经下载到磁盘的完整或部分文件。
