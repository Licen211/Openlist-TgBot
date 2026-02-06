# OpenList Telegram Bot

一个用于通过 Telegram 控制 OpenList 的机器人：

- 从 OpenList 下载文件到 Telegram
- 把 Telegram 文档上传到 OpenList
- 发送磁力链接给 OpenList 创建离线下载任务
- 自己选择任务目录并执行任务

## 功能

- `/start`：显示帮助
- `/download <远程文件路径>`：从 OpenList 下载文件并回传到 Telegram
  - 示例：`/download /Movies/demo.mp4`
- 发送文档并附带 caption：`/upload <远程目录或完整路径>`
  - 如果是目录，自动使用 Telegram 原文件名
  - 示例：`/upload /Uploads/`
  - 示例：`/upload /Uploads/report.pdf`
- `/mkdir <远程目录路径>`：创建目录（优先 OpenList API，失败回退 WebDAV）
- `/setdir <远程目录>`：设置你自己的默认任务目录
- `/getdir`：查看你当前默认任务目录
- `/settool <aria2|qb>`：设置你的默认离线下载方式
- `/gettool`：查看你当前离线下载方式
- `/magnet <磁力链接>`：发送后弹出目录选择器，再创建离线下载任务
- `/magnet <远程目录> <磁力链接>`：指定目录创建离线下载任务
- `/magnet <aria2|qb> <磁力链接>`：手动选择离线下载方式并再选目录
- `/tasks`：查询 OpenList 离线下载任务进度
- 直接发送 `magnet:?` 开头文本：自动用你当前默认目录创建离线下载任务

## 一键安装与管理菜单

你可以直接运行安装脚本，包含交互式菜单，方便后期随时修改密钥：

```bash
chmod +x install.sh
./install.sh
```

菜单功能包括：

- 一键安装并启动
- 安装/更新依赖
- 配置密钥和参数（`.env`）
  - 新增快捷配置子菜单，可按项单独修改
  - 可一键选择默认离线工具：`aria2` / `qb`
  - 可分别设置 Bot Token、OpenList API Token、用户名/密码、接口路径等
- 启动/停止机器人
- 查看运行状态与日志

## 快速开始

1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. 配置环境变量

复制 `.env.example` 到 `.env` 并填写：

```bash
cp .env.example .env
```

3. 启动

```bash
python bot.py
```

## 环境变量

> 如果你只填 `do.Licen.live:525`（不带 `http://` 或 `https://`），程序会自动按 `http://` 处理。

### Telegram

- `TELEGRAM_BOT_TOKEN`：Telegram Bot Token
- `ALLOWED_USER_IDS`：允许控制机器人的 Telegram 用户 ID，逗号分隔（可选）

### OpenList WebDAV（用于上传 / 下载，mkdir 也可作为回退）

- `OPENLIST_WEBDAV_URL`：OpenList WebDAV 地址（例如：`http://do.Licen.live:525/dav`）。可留空，程序会按 `OPENLIST_API_URL + /dav` 自动补齐
- `OPENLIST_USERNAME`：OpenList 用户名
- `OPENLIST_PASSWORD`：OpenList 密码

### OpenList API（用于磁力离线下载任务、目录创建、目录浏览）

- `OPENLIST_API_URL`：OpenList 主地址（例如：`http://do.Licen.live:525`）
- `OPENLIST_API_TOKEN`：OpenList API Token
- `OPENLIST_OFFLINE_ENDPOINT`：离线下载 API 路径（默认：`/api/fs/add_offline_download`）
- `OPENLIST_MKDIR_ENDPOINT`：创建目录 API 路径（默认：`/api/fs/mkdir`）
- `OPENLIST_LIST_ENDPOINT`：目录浏览 API 路径（默认：`/api/fs/list`）
- `OPENLIST_OFFLINE_LIST_ENDPOINT`：离线任务列表 API 路径（默认：`/api/task/offline_download/list`）
- `OPENLIST_DEFAULT_DOWNLOAD_DIR`：全局默认下载目录（默认：`/downloads`）
- `OPENLIST_DEFAULT_OFFLINE_TOOL`：全局默认离线下载方式（`aria2` 或 `qb`，默认：`aria2`）

## 注意

- 上传和下载大文件会消耗较多内存和带宽。
- Telegram 对文件大小有平台限制。
- 磁力任务是否可用取决于 OpenList 后端是否已配置离线下载工具（如 aria2）。
- `/setdir` 的目录选择保存在进程内存中，重启机器人后会恢复为 `OPENLIST_DEFAULT_DOWNLOAD_DIR`。


## 打包项目文件

如需一键打包当前项目文件，可执行：

```bash
chmod +x package.sh
./package.sh
```

打包产物会生成在 `dist/` 目录下（`.tar.gz`），并自动排除 `.git`、`.venv`、`__pycache__`。


### 你的地址示例（非 HTTPS）

在 `.env` 里可直接这样配置：

```env
OPENLIST_API_URL=do.Licen.live:525
OPENLIST_WEBDAV_URL=do.Licen.live:525/dav
```

程序会自动补成 `http://`。



## 手动上传到 GitHub

如果你需要在网络受限场景下手动上传，请查看：`docs/MANUAL_UPLOAD.md`。

另外如果你要在平板上直接下载打包文件，可以按文档里的“给平板一个可直接点击的下载链接”章节，用 `python3 -m http.server` 临时共享 `dist/` 目录。

如果你在网页里使用我但发现给的是服务器路径，可看同一文档里的“为什么我在网页里用你，却让你去服务器执行命令”说明。

如果你不知道服务器 IP，也可看同一文档里的“我怎么知道服务器 IP？”章节。

如果你没有服务器也没有本地文件，可看同一文档里的“我没有服务器，也没有本地文件，怎么拿到项目？”章节。

## Ubuntu 服务器部署建议

推荐在 Ubuntu 20.04+/22.04+ 上按下面顺序部署：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
cd /path/to/Openlist-TgBot
chmod +x install.sh
./install.sh
```

在安装菜单中建议至少配置这些项：

- `TELEGRAM_BOT_TOKEN`
- `OPENLIST_API_URL`（你的地址可填：`do.Licen.live:525`，程序会自动补 `http://`）
- `OPENLIST_API_TOKEN`
- `OPENLIST_USERNAME` / `OPENLIST_PASSWORD`
- `OPENLIST_DEFAULT_OFFLINE_TOOL`（`aria2` 或 `qb`）

部署后可通过菜单的「查看运行状态」和「查看最近日志」确认服务状态。
