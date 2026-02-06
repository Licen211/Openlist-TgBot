# 手动上传指南（GitHub）

如果当前环境无法直接推送到 GitHub，可以按下面步骤手动上传。

## 1) 打包项目

在项目根目录执行：

```bash
chmod +x package.sh
./package.sh
```

打包完成后，压缩包会在 `dist/` 目录下，例如：

- `dist/Openlist-TgBot-20260206-xxxxxx.tar.gz`

## 2) 在本机解压（可选）

如果你想先检查文件：

```bash
tar -xzf dist/Openlist-TgBot-*.tar.gz
```

## 3) 上传到你的 GitHub 仓库

以你的仓库 `https://github.com/Licen211/Openlist-TgBot.git` 为例。

### 方式 A：直接在当前目录推送（推荐）

```bash
git init
git add .
git commit -m "chore: upload Openlist-TgBot"
git branch -M main
git remote add origin https://github.com/Licen211/Openlist-TgBot.git
git push -u origin main
```

> 如果仓库已有历史，先执行 `git pull --rebase origin main` 解决差异后再推送。

### 方式 B：网页上传压缩包内容

1. 打开仓库页面：`https://github.com/Licen211/Openlist-TgBot`
2. 选择 **Add file** -> **Upload files**
3. 把解压后的文件拖进去
4. 填写提交说明，点击 **Commit changes**

## 4) 服务器部署最小步骤

上传完成后，在你的 Ubuntu 服务器：

```bash
git clone https://github.com/Licen211/Openlist-TgBot.git
cd Openlist-TgBot
chmod +x install.sh
./install.sh
```

然后在安装菜单里填写：

- `TELEGRAM_BOT_TOKEN`
- `OPENLIST_API_URL=do.Licen.live:525`
- `OPENLIST_API_TOKEN`
- `OPENLIST_USERNAME`
- `OPENLIST_PASSWORD`
- `OPENLIST_DEFAULT_OFFLINE_TOOL`（`aria2` 或 `qb`）

> 你的地址不带协议时，程序会自动按 `http://` 处理。


## 5) 给平板一个可直接点击的下载链接

你之前看到的 `dist/xxx.tar.gz` 是**服务器本地路径**，不是公网 URL，所以不能直接在平板点开。

如果你的 Ubuntu 服务器和你的平板在同一网络（或服务器端口可访问），可临时开启 HTTP 文件服务：

```bash
cd /workspace/Openlist-TgBot/dist
python3 -m http.server 8080 --bind 0.0.0.0
```

然后在平板浏览器打开：

```text
http://<你的服务器IP>:8080/Openlist-TgBot-20260206-xxxxxx.tar.gz
```

示例：

```text
http://192.168.1.20:8080/Openlist-TgBot-20260206-063540.tar.gz
```

如果打不开，请检查：

- 服务器防火墙是否放行 8080 端口（如 `ufw allow 8080`）
- 云服务器安全组是否放行 8080
- 平板与服务器网络是否互通

下载完成后，按 `Ctrl + C` 停止临时文件服务。
