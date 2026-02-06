import logging
import os
from io import BytesIO
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)



def normalize_base_url(url: str) -> str:
    value = url.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"http://{value}"
    return value.rstrip("/")

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENLIST_USERNAME = os.getenv("OPENLIST_USERNAME", "")
OPENLIST_PASSWORD = os.getenv("OPENLIST_PASSWORD", "")
OPENLIST_API_URL = normalize_base_url(os.getenv("OPENLIST_API_URL", ""))
WEBDAV_URL = normalize_base_url(os.getenv("OPENLIST_WEBDAV_URL", ""))
if not WEBDAV_URL and OPENLIST_API_URL:
    WEBDAV_URL = OPENLIST_API_URL + "/dav"
OPENLIST_API_TOKEN = os.getenv("OPENLIST_API_TOKEN", "")
OPENLIST_OFFLINE_ENDPOINT = os.getenv(
    "OPENLIST_OFFLINE_ENDPOINT", "/api/fs/add_offline_download"
)
OPENLIST_MKDIR_ENDPOINT = os.getenv("OPENLIST_MKDIR_ENDPOINT", "/api/fs/mkdir")
OPENLIST_LIST_ENDPOINT = os.getenv("OPENLIST_LIST_ENDPOINT", "/api/fs/list")
OPENLIST_OFFLINE_LIST_ENDPOINT = os.getenv(
    "OPENLIST_OFFLINE_LIST_ENDPOINT", "/api/task/offline_download/list"
)
OPENLIST_DEFAULT_DOWNLOAD_DIR = os.getenv("OPENLIST_DEFAULT_DOWNLOAD_DIR", "/downloads")
OPENLIST_DEFAULT_OFFLINE_TOOL = os.getenv("OPENLIST_DEFAULT_OFFLINE_TOOL", "aria2")
ALLOWED_USER_IDS = {
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip().isdigit()
}

USER_SELECTED_DIRS: dict[int, str] = {}
USER_SELECTED_TOOLS: dict[int, str] = {}
MAGNET_PICK_SESSIONS: dict[str, dict[str, str | int]] = {}
MAGNET_PICK_SEQ = 0


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def normalize_remote_path(remote_path: str) -> str:
    remote_path = remote_path.strip()
    if not remote_path.startswith("/"):
        remote_path = "/" + remote_path
    return remote_path


def build_webdav_url(remote_path: str) -> str:
    normalized = normalize_remote_path(remote_path)
    segments = [quote(seg) for seg in normalized.split("/")]
    return WEBDAV_URL + "/".join(segments)


def build_openlist_api_url(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return OPENLIST_API_URL + endpoint


def get_openlist_api_headers() -> dict[str, str]:
    return {
        "Authorization": OPENLIST_API_TOKEN,
        "Content-Type": "application/json",
    }


def get_user_download_dir(user_id: int | None) -> str:
    if user_id is None:
        return OPENLIST_DEFAULT_DOWNLOAD_DIR
    return USER_SELECTED_DIRS.get(user_id, OPENLIST_DEFAULT_DOWNLOAD_DIR)




def normalize_offline_tool(tool: str) -> str:
    lowered = tool.strip().lower()
    if lowered in ("qb", "qbit", "qbittorrent"):
        return "qb"
    return "aria2"


def get_user_offline_tool(user_id: int | None) -> str:
    if user_id is None:
        return normalize_offline_tool(OPENLIST_DEFAULT_OFFLINE_TOOL)
    return USER_SELECTED_TOOLS.get(user_id, normalize_offline_tool(OPENLIST_DEFAULT_OFFLINE_TOOL))

def next_magnet_session_id() -> str:
    global MAGNET_PICK_SEQ
    MAGNET_PICK_SEQ += 1
    return f"m{MAGNET_PICK_SEQ}"


def list_openlist_dirs(path: str) -> tuple[bool, list[str] | str]:
    if not OPENLIST_API_URL or not OPENLIST_API_TOKEN:
        return False, "未配置 OPENLIST_API_URL 或 OPENLIST_API_TOKEN，无法浏览目录。"

    normalized_path = normalize_remote_path(path)
    api_url = build_openlist_api_url(OPENLIST_LIST_ENDPOINT)
    payload = {
        "path": normalized_path,
        "password": "",
        "page": 1,
        "per_page": 0,
        "refresh": False,
    }

    try:
        resp = requests.post(
            api_url,
            headers=get_openlist_api_headers(),
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            return False, f"列目录失败，HTTP {resp.status_code}: {resp.text[:200]}"

        body = resp.json()
        code = body.get("code")
        if code not in (200, 0, None):
            return False, f"列目录失败，code={code}, message={body.get('message', '')}"

        content = body.get("data", {}).get("content", [])
        dirs: list[str] = []
        for item in content:
            if item.get("is_dir"):
                name = item.get("name")
                if name:
                    dirs.append(name)
        dirs.sort()
        return True, dirs
    except (requests.RequestException, ValueError) as exc:
        return False, f"列目录失败: {exc}"


def build_magnet_dir_keyboard(session_id: str, current_path: str) -> InlineKeyboardMarkup:
    ok, result = list_openlist_dirs(current_path)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton("✅ 选择当前目录", callback_data=f"mag:pick:{session_id}")])

    if current_path != "/":
        parent = os.path.dirname(current_path.rstrip("/")) or "/"
        rows.append([InlineKeyboardButton("⬆️ 上一级", callback_data=f"mag:go:{session_id}:{parent}")])

    if ok:
        for dirname in result:
            next_path = normalize_remote_path(f"{current_path.rstrip('/')}/{dirname}")
            rows.append(
                [InlineKeyboardButton(f"📁 {dirname}", callback_data=f"mag:go:{session_id}:{next_path}")]
            )
    else:
        rows.append([InlineKeyboardButton(f"⚠️ {result}", callback_data=f"mag:noop:{session_id}")])

    rows.append([InlineKeyboardButton("❌ 取消", callback_data=f"mag:cancel:{session_id}")])
    return InlineKeyboardMarkup(rows)


def format_task_progress(task: dict) -> str:
    name = task.get("name") or task.get("title") or task.get("url") or "(未命名任务)"
    status = str(task.get("status") or task.get("state") or task.get("phase") or "unknown")
    progress = task.get("progress")
    if progress is None:
        progress = task.get("percent")

    progress_text = "未知"
    if isinstance(progress, (int, float)):
        if progress <= 1:
            progress_text = f"{progress * 100:.1f}%"
        else:
            progress_text = f"{progress:.1f}%"
    elif isinstance(progress, str) and progress.strip():
        progress_text = progress

    speed = task.get("speed") or task.get("download_speed") or "-"
    return f"- {name}\n  状态: {status} | 进度: {progress_text} | 速度: {speed}"


def list_offline_tasks() -> tuple[bool, list[dict] | str]:
    if not OPENLIST_API_URL or not OPENLIST_API_TOKEN:
        return False, "未配置 OPENLIST_API_URL 或 OPENLIST_API_TOKEN，无法查询离线任务。"

    endpoint_candidates = [
        OPENLIST_OFFLINE_LIST_ENDPOINT,
        "/api/task/offline_download/list",
        "/api/admin/task/offline_download/list",
    ]
    payload_candidates = [
        {"page": 1, "per_page": 20},
        {"page": 1, "per_page": 20, "status": ""},
        {},
    ]

    last_error = ""
    for endpoint in endpoint_candidates:
        api_url = build_openlist_api_url(endpoint)
        for payload in payload_candidates:
            try:
                resp = requests.post(
                    api_url,
                    headers=get_openlist_api_headers(),
                    json=payload,
                    timeout=30,
                )
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    continue

                body = resp.json()
                code = body.get("code")
                if code not in (200, 0, None):
                    last_error = f"API code={code}, message={body.get('message', '')}"
                    continue

                data = body.get("data")
                tasks: list[dict] = []
                if isinstance(data, dict):
                    if isinstance(data.get("content"), list):
                        tasks = data.get("content", [])
                    elif isinstance(data.get("list"), list):
                        tasks = data.get("list", [])
                    elif isinstance(data.get("items"), list):
                        tasks = data.get("items", [])
                elif isinstance(data, list):
                    tasks = data

                return True, tasks
            except (requests.RequestException, ValueError) as exc:
                last_error = str(exc)

    return False, f"查询离线任务失败: {last_error}"


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    await update.message.reply_text("正在查询 OpenList 离线下载任务...")
    ok, result = list_offline_tasks()
    if not ok:
        await update.message.reply_text(str(result))
        return

    tasks = result
    if not tasks:
        await update.message.reply_text("当前没有离线下载任务。")
        return

    lines = ["离线下载任务进度（最多显示20条）:"]
    for task in tasks[:20]:
        lines.append(format_task_progress(task))
    await update.message.reply_text("\n".join(lines))


async def require_auth(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if is_allowed(user.id):
        return True
    await update.effective_message.reply_text("你没有权限使用这个机器人。")
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    await update.message.reply_text(
        "可用命令:\n"
        "/download <远程文件路径> - 从 OpenList 下载文件\n"
        "/mkdir <远程目录路径> - 在 OpenList 创建目录\n"
        "/setdir <远程目录> - 设置你的默认任务目录\n"
        "/getdir - 查看你当前默认任务目录\n"
        "/settool <aria2|qb> - 设置默认离线下载方式\n"
        "/gettool - 查看当前离线下载方式\n"
        "/magnet <磁力链接> - 发送后弹出目录选择器\n"
        "/magnet <远程目录> <磁力链接> - 指定目录直接创建任务\n"
        "/magnet <aria2|qb> <磁力链接> - 指定下载方式并选择目录\n"
        "/tasks - 查询离线下载任务进度\n\n"
        "上传方式:\n"
        "发送文档并在 caption 写: /upload <远程目录或完整路径>\n"
        "也可以直接发送 magnet:? 开头的磁力链接"
    )


async def setdir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    if not context.args:
        await update.message.reply_text("用法: /setdir <远程目录>")
        return

    user = update.effective_user
    target_dir = normalize_remote_path(" ".join(context.args).strip())
    USER_SELECTED_DIRS[user.id] = target_dir
    await update.message.reply_text(f"已设置默认目录: {target_dir}")


async def getdir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    current_dir = get_user_download_dir(user.id if user else None)
    await update.message.reply_text(f"你当前默认目录: {current_dir}")




async def settool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    if not context.args:
        await update.message.reply_text("用法: /settool <aria2|qb>")
        return

    user = update.effective_user
    if not user:
        return

    raw = context.args[0].strip().lower()
    if raw not in ("aria2", "qb", "qbit", "qbittorrent"):
        await update.message.reply_text("仅支持: aria2 或 qb")
        return

    tool = normalize_offline_tool(raw)
    USER_SELECTED_TOOLS[user.id] = tool
    await update.message.reply_text(f"已设置默认离线下载方式: {tool}")


async def gettool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    tool = get_user_offline_tool(user.id if user else None)
    await update.message.reply_text(f"你当前离线下载方式: {tool}")

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    if not context.args:
        await update.message.reply_text("用法: /download <远程文件路径>")
        return

    remote_path = " ".join(context.args).strip()
    if not remote_path:
        await update.message.reply_text("远程文件路径不能为空。")
        return

    file_name = os.path.basename(remote_path.rstrip("/")) or "download.bin"
    url = build_webdav_url(remote_path)

    await update.message.reply_text(f"开始下载: {remote_path}")
    try:
        resp = requests.get(
            url,
            auth=(OPENLIST_USERNAME, OPENLIST_PASSWORD),
            stream=True,
            timeout=120,
        )
        if resp.status_code != 200:
            await update.message.reply_text(f"下载失败，HTTP {resp.status_code}")
            return

        data = BytesIO(resp.content)
        data.name = file_name
        data.seek(0)
        await update.message.reply_document(document=data, filename=file_name)
    except requests.RequestException as exc:
        logger.exception("Download failed")
        await update.message.reply_text(f"下载失败: {exc}")


async def mkdir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    if not context.args:
        await update.message.reply_text("用法: /mkdir <远程目录路径>")
        return

    target = " ".join(context.args).strip()
    if not target:
        await update.message.reply_text("目录路径不能为空。")
        return

    ok, api_message = create_folder_by_api(target)
    if ok:
        await update.message.reply_text(api_message)
        return

    parts = [p for p in target.split("/") if p]
    current = ""
    try:
        for part in parts:
            current += f"/{part}"
            url = build_webdav_url(current + "/")
            resp = requests.request(
                "MKCOL", url, auth=(OPENLIST_USERNAME, OPENLIST_PASSWORD), timeout=30
            )
            if resp.status_code not in (201, 405):
                await update.message.reply_text(
                    f"创建目录失败: {current} (HTTP {resp.status_code})"
                )
                return
        await update.message.reply_text(f"目录已就绪: {normalize_remote_path(target)}")
    except requests.RequestException as exc:
        logger.exception("MKCOL failed")
        if api_message:
            await update.message.reply_text(f"API 创建失败，回退 WebDAV 也失败: {api_message}; {exc}")
        else:
            await update.message.reply_text(f"创建目录失败: {exc}")


def resolve_upload_path(upload_target: str, filename: str) -> str:
    upload_target = upload_target.strip()
    if upload_target.endswith("/"):
        return upload_target + filename
    if "." not in os.path.basename(upload_target):
        return upload_target.rstrip("/") + "/" + filename
    return upload_target


def parse_magnet_input(
    args: list[str], default_target_dir: str
) -> tuple[str, str, str] | tuple[None, None, None]:
    if not args:
        return None, None, None

    default_tool = normalize_offline_tool(OPENLIST_DEFAULT_OFFLINE_TOOL)
    first = args[0].strip().lower()

    if first in ("aria2", "qb", "qbit", "qbittorrent"):
        selected_tool = normalize_offline_tool(first)
        rest = args[1:]
        if not rest:
            return None, None, None
        joined = " ".join(rest).strip()
        if joined.startswith("magnet:?"):
            return default_target_dir, joined, selected_tool
        if len(rest) >= 2:
            target = rest[0]
            magnet_link = " ".join(rest[1:]).strip()
            if magnet_link.startswith("magnet:?"):
                return target, magnet_link, selected_tool
        return None, None, None

    joined = " ".join(args).strip()
    if joined.startswith("magnet:?"):
        return default_target_dir, joined, default_tool

    if len(args) >= 2:
        target = args[0]
        magnet_link = " ".join(args[1:]).strip()
        if magnet_link.startswith("magnet:?"):
            return target, magnet_link, default_tool
    return None, None, None


def create_offline_download_task(
    target_dir: str, magnet_link: str, offline_tool: str
) -> tuple[bool, str]:
    if not OPENLIST_API_URL or not OPENLIST_API_TOKEN:
        return False, "未配置 OPENLIST_API_URL 或 OPENLIST_API_TOKEN，无法创建离线下载任务。"

    api_url = build_openlist_api_url(OPENLIST_OFFLINE_ENDPOINT)
    normalized_target = normalize_remote_path(target_dir)
    headers = get_openlist_api_headers()
    tool = normalize_offline_tool(offline_tool)

    base_payloads = [
        {"path": normalized_target, "urls": [magnet_link]},
        {"path": normalized_target, "url": magnet_link},
        {"dir": normalized_target, "url": magnet_link},
    ]

    payload_candidates: list[dict] = []
    for payload in base_payloads:
        payload_candidates.append(payload)
        payload_candidates.append({**payload, "tool": tool})
        payload_candidates.append({**payload, "method": tool})
        payload_candidates.append({**payload, "provider": tool})
        payload_candidates.append({**payload, "type": tool})

    last_error = ""
    for payload in payload_candidates:
        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                continue

            body = resp.json()
            code = body.get("code")
            message = body.get("message", "")
            if code in (200, 0, None):
                return True, f"离线下载任务已创建到目录: {normalized_target}，方式: {tool}"

            last_error = f"API code={code}, message={message}"
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)

    return False, f"创建离线下载任务失败: {last_error}"


def create_folder_by_api(target_dir: str) -> tuple[bool, str]:
    if not OPENLIST_API_URL or not OPENLIST_API_TOKEN:
        return False, ""

    normalized_target = normalize_remote_path(target_dir).rstrip("/")
    if not normalized_target:
        return False, "目录路径不能为空。"

    parent_dir = os.path.dirname(normalized_target) or "/"
    folder_name = os.path.basename(normalized_target)
    api_url = build_openlist_api_url(OPENLIST_MKDIR_ENDPOINT)
    headers = get_openlist_api_headers()

    payload_candidates = [
        {"path": parent_dir, "name": folder_name},
        {"path": normalized_target},
        {"dir": normalized_target},
    ]

    last_error = ""
    for payload in payload_candidates:
        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                continue

            body = resp.json()
            code = body.get("code")
            message = body.get("message", "")
            if code in (200, 0, None):
                return True, f"目录已创建: {normalized_target}"

            if "exists" in message.lower() or "已存在" in message:
                return True, f"目录已存在: {normalized_target}"
            last_error = f"API code={code}, message={message}"
        except (requests.RequestException, ValueError) as exc:
            last_error = str(exc)

    return False, last_error


async def magnet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    if not user:
        return

    if not context.args:
        await update.message.reply_text(
            "用法:\n"
            "/magnet <磁力链接>\n"
            "/magnet <远程目录> <磁力链接>\n"
            "/magnet <aria2|qb> <磁力链接>"
        )
        return

    default_target_dir = get_user_download_dir(user.id)
    default_tool = get_user_offline_tool(user.id)

    raw_first = context.args[0].strip().lower()
    inline_tool = None
    inline_args = context.args
    if raw_first in ("aria2", "qb", "qbit", "qbittorrent"):
        inline_tool = normalize_offline_tool(raw_first)
        inline_args = context.args[1:]

    joined = " ".join(inline_args).strip()
    if joined.startswith("magnet:?"):
        session_id = next_magnet_session_id()
        chosen_tool = inline_tool or default_tool
        MAGNET_PICK_SESSIONS[session_id] = {
            "user_id": user.id,
            "magnet": joined,
            "path": default_target_dir,
            "tool": chosen_tool,
        }
        keyboard = build_magnet_dir_keyboard(session_id, default_target_dir)
        await update.message.reply_text(
            f"请选择下载目录（当前: {default_target_dir}，方式: {chosen_tool}）",
            reply_markup=keyboard,
        )
        return

    target_dir, magnet_link, tool = parse_magnet_input(context.args, default_target_dir)
    if not target_dir or not magnet_link or not tool:
        await update.message.reply_text(
            "用法:\n"
            "/magnet <磁力链接>\n"
            "/magnet <远程目录> <磁力链接>\n"
            "/magnet <aria2|qb> <磁力链接>"
        )
        return

    await update.message.reply_text(f"正在创建离线下载任务，目标目录: {target_dir}，方式: {tool}")
    _, message = create_offline_download_task(target_dir, magnet_link, tool)
    await update.message.reply_text(message)


async def magnet_dir_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("mag:"):
        return

    parts = query.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    session = MAGNET_PICK_SESSIONS.get(session_id)
    if not session:
        await query.answer("会话已失效，请重新发送 /magnet", show_alert=True)
        return

    if int(session.get("user_id", -1)) != user.id:
        await query.answer("这个选择器不是你的。", show_alert=True)
        return

    if action == "noop":
        await query.answer("当前目录读取失败")
        return

    if action == "cancel":
        MAGNET_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text("已取消创建下载任务。")
        await query.answer()
        return

    if action == "go":
        new_path = normalize_remote_path(extra or "/")
        session["path"] = new_path
        keyboard = build_magnet_dir_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择下载目录（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "pick":
        target_dir = normalize_remote_path(str(session.get("path", "/")))
        magnet_link = str(session.get("magnet", ""))
        tool = normalize_offline_tool(str(session.get("tool", OPENLIST_DEFAULT_OFFLINE_TOOL)))
        MAGNET_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text(f"正在创建离线下载任务，目标目录: {target_dir}，方式: {tool}")
        _, message = create_offline_download_task(target_dir, magnet_link, tool)
        await query.message.reply_text(message)
        await query.answer("已提交")
        return

    await query.answer("未知操作")


async def magnet_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    msg = update.message
    if msg is None or not msg.text:
        return

    text = msg.text.strip()
    if not text.startswith("magnet:?"):
        return

    user = update.effective_user
    if not user:
        return

    target_dir = get_user_download_dir(user.id)
    tool = get_user_offline_tool(user.id)
    await msg.reply_text(f"收到磁力链接，正在创建离线下载任务（目录: {target_dir}，方式: {tool}）")
    _, message = create_offline_download_task(target_dir, text, tool)
    await msg.reply_text(message)


async def upload_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    msg = update.message
    if msg is None or msg.document is None:
        return

    caption = msg.caption or ""
    if not caption.strip().startswith("/upload"):
        await msg.reply_text("请使用 caption: /upload <远程目录或完整路径>")
        return

    parts = caption.strip().split(maxsplit=1)
    if len(parts) < 2:
        await msg.reply_text("用法: 在文档 caption 里写 /upload <远程目录或完整路径>")
        return

    remote_target = resolve_upload_path(parts[1], msg.document.file_name)
    url = build_webdav_url(remote_target)

    await msg.reply_text(f"开始上传到: {remote_target}")
    try:
        tg_file = await context.bot.get_file(msg.document.file_id)
        buf = BytesIO()
        await tg_file.download_to_memory(out=buf)
        buf.seek(0)

        resp = requests.put(
            url,
            auth=(OPENLIST_USERNAME, OPENLIST_PASSWORD),
            data=buf.read(),
            timeout=120,
        )
        if resp.status_code not in (200, 201, 204):
            await msg.reply_text(f"上传失败，HTTP {resp.status_code}")
            return

        await msg.reply_text("上传成功。")
    except requests.RequestException as exc:
        logger.exception("Upload failed")
        await msg.reply_text(f"上传失败: {exc}")


def validate_env() -> None:
    required = {
        "TELEGRAM_BOT_TOKEN": BOT_TOKEN,
        "OPENLIST_WEBDAV_URL": WEBDAV_URL,
        "OPENLIST_USERNAME": OPENLIST_USERNAME,
        "OPENLIST_PASSWORD": OPENLIST_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"缺少环境变量: {', '.join(missing)}")


def main() -> None:
    validate_env()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_file))
    app.add_handler(CommandHandler("mkdir", mkdir))
    app.add_handler(CommandHandler("setdir", setdir))
    app.add_handler(CommandHandler("getdir", getdir))
    app.add_handler(CommandHandler("settool", settool))
    app.add_handler(CommandHandler("gettool", gettool))
    app.add_handler(CommandHandler("magnet", magnet_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CallbackQueryHandler(magnet_dir_picker_callback, pattern=r"^mag:"))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_document))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, magnet_text_handler),
    )

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
