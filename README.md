# MadokaBot

樋口円香机器人，正在开发中…


# 内置插件
通用
通用指令集合，包含设置、查询和商店功能

回应
使用Ping方法，简单测试机器人状态

签到
签到插件

绘图Pillow
用于支持各种绘图方法

图片制图
使用音乐模板生成图片：`/制图 音乐 <图片> [模板] [标题] [子标题]`，默认模板为 1，标题为群昵称，子标题为 QQ 号

戳戳
戳一戳回应

RSS订阅
基于 ELF_RSS 适配的 RSS/RSSHub 动态订阅、更新推送、图片处理、去重及可选 aria2 种子下载上传（内容按原文展示）

链接解析
从 nonebot-plugin-resolver 复制并针对 MadokaBot 独立改造，支持 Bilibili、抖音、TikTok、ACFun、X、小红书、YouTube、网易云、酷狗和微博链接。临时文件统一写入 LocalStore 缓存目录。


# 引用插件

zhaomaoniu/nonebot-plugin-steam-info
steam插件，查询好友在线状态，推送好友游戏上线/离线消息
此插件针对MadokaBot进行特殊适配


# 全局网络配置

MadokaBot 统一使用 `madoka_bundle` 主配置中的 `PROXY` 作为网络代理。需要代理的内置或外部插件应直接读取 `madokabot.madoka_bundle.config.config.proxy`，不再单独添加代理配置。

```dotenv
PROXY="http://127.0.0.1:1081"
```
