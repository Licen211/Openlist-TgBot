import logging
import os
from io import BytesIO
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
QBIT_BASE_URL = normalize_base_url(os.getenv("QBIT_BASE_URL", ""))
QBIT_USERNAME = os.getenv("QBIT_USERNAME", "")
QBIT_PASSWORD = os.getenv("QBIT_PASSWORD", "")
ARIA2_RPC_URL = os.getenv("ARIA2_RPC_URL", "").strip()
ARIA2_RPC_SECRET = os.getenv("ARIA2_RPC_SECRET", "")
ALLOWED_USER_IDS = {
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip().isdigit()
}

USER_SELECTED_DIRS: dict[int, str] = {}
USER_SELECTED_TOOLS: dict[int, str] = {}
USER_PENDING_UPLOAD_DIRS: dict[int, str] = {}
USER_PENDING_MKDIR_PARENTS: dict[int, str] = {}
MAGNET_PICK_SESSIONS: dict[str, dict[str, str | int]] = {}
MAGNET_PICK_SEQ = 0
DIR_PICK_SESSIONS: dict[str, dict[str, str | int]] = {}
DIR_PICK_SEQ = 0
DOWNLOAD_PICK_SESSIONS: dict[str, dict[str, str | int]] = {}
DOWNLOAD_PICK_SEQ = 0
UPLOAD_PICK_SESSIONS: dict[str, dict[str, str | int]] = {}
UPLOAD_PICK_SEQ = 0
MKDIR_PICK_SESSIONS: dict[str, dict[str, str | int]] = {}
MKDIR_PICK_SEQ = 0


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def has_webdav_config() -> bool:
    return bool(WEBDAV_URL and OPENLIST_USERNAME and OPENLIST_PASSWORD)


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


def next_dir_session_id() -> str:
    global DIR_PICK_SEQ
    DIR_PICK_SEQ += 1
    return f"d{DIR_PICK_SEQ}"


def next_download_session_id() -> str:
    global DOWNLOAD_PICK_SEQ
    DOWNLOAD_PICK_SEQ += 1
    return f"dl{DOWNLOAD_PICK_SEQ}"


def next_upload_session_id() -> str:
    global UPLOAD_PICK_SEQ
    UPLOAD_PICK_SEQ += 1
    return f"up{UPLOAD_PICK_SEQ}"


def next_mkdir_session_id() -> str:
    global MKDIR_PICK_SEQ
    MKDIR_PICK_SEQ += 1
    return f"mk{MKDIR_PICK_SEQ}"


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


def list_openlist_entries(path: str) -> tuple[bool, tuple[list[str], list[str]] | str]:
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
        files: list[str] = []
        for item in content:
            name = item.get("name")
            if not name:
                continue
            if item.get("is_dir"):
                dirs.append(name)
            else:
                files.append(name)
        dirs.sort()
        files.sort()
        return True, (dirs, files)
    except (requests.RequestException, ValueError) as exc:
        return False, f"列目录失败: {exc}"


async def open_setdir_picker(user_id: int, message) -> None:
    session_id = next_dir_session_id()
    default_dir = get_user_download_dir(user_id)
    DIR_PICK_SESSIONS[session_id] = {
        "user_id": user_id,
        "path": default_dir,
    }
    keyboard = build_dir_picker_keyboard(session_id, default_dir)
    await message.reply_text(
        f"请选择要设置的默认目录（当前: {default_dir}）",
        reply_markup=keyboard,
    )


async def open_upload_picker(user_id: int, message) -> None:
    session_id = next_upload_session_id()
    default_dir = get_user_download_dir(user_id)
    UPLOAD_PICK_SESSIONS[session_id] = {
        "user_id": user_id,
        "path": default_dir,
    }
    keyboard = build_upload_dir_keyboard(session_id, default_dir)
    await message.reply_text(
        f"请选择上传目录（当前: {default_dir}）",
        reply_markup=keyboard,
    )


async def open_download_picker(user_id: int, message) -> None:
    session_id = next_download_session_id()
    default_dir = get_user_download_dir(user_id)
    DOWNLOAD_PICK_SESSIONS[session_id] = {
        "user_id": user_id,
        "path": default_dir,
    }
    keyboard = build_download_picker_keyboard(session_id, default_dir)
    await message.reply_text(
        f"请选择要下载的文件（当前目录: {default_dir}）",
        reply_markup=keyboard,
    )


async def open_mkdir_picker(user_id: int, message) -> None:
    session_id = next_mkdir_session_id()
    default_dir = get_user_download_dir(user_id)
    MKDIR_PICK_SESSIONS[session_id] = {
        "user_id": user_id,
        "path": default_dir,
    }
    keyboard = build_mkdir_dir_keyboard(session_id, default_dir)
    await message.reply_text(
        f"请选择要创建目录的父路径（当前: {default_dir}）",
        reply_markup=keyboard,
    )


def _set_picker_entries(session: dict, entries: list[dict]) -> None:
    session["entries"] = entries


def _get_entry_path(session: dict, entry_id: str) -> str | None:
    entries = session.get("entries", [])
    if not isinstance(entries, list):
        return None
    if not entry_id.isdigit():
        return None
    index = int(entry_id)
    if 0 <= index < len(entries):
        entry = entries[index]
        if isinstance(entry, dict):
            path = entry.get("path")
            if isinstance(path, str):
                return path
    return None


def build_magnet_dir_keyboard(session_id: str, current_path: str) -> InlineKeyboardMarkup:
    ok, result = list_openlist_dirs(current_path)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton("✅ 选择此目录", callback_data=f"mag:pick:{session_id}")])

    if current_path != "/":
        rows.append([InlineKeyboardButton("⬆️ 上一级", callback_data=f"mag:up:{session_id}")])

    entries: list[dict] = []
    if ok:
        for dirname in result:
            next_path = normalize_remote_path(f"{current_path.rstrip('/')}/{dirname}")
            entries.append({"type": "dir", "path": next_path})
            entry_id = str(len(entries) - 1)
            rows.append(
                [InlineKeyboardButton(f"📁 {dirname}", callback_data=f"mag:go:{session_id}:{entry_id}")]
            )
    else:
        rows.append([InlineKeyboardButton(f"⚠️ {result}", callback_data=f"mag:noop:{session_id}")])

    session = MAGNET_PICK_SESSIONS.get(session_id)
    if session is not None:
        _set_picker_entries(session, entries)

    rows.append([InlineKeyboardButton("❌ 取消", callback_data=f"mag:cancel:{session_id}")])
    return InlineKeyboardMarkup(rows)


def build_dir_picker_keyboard(session_id: str, current_path: str) -> InlineKeyboardMarkup:
    ok, result = list_openlist_dirs(current_path)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton("✅ 选择此目录", callback_data=f"dir:pick:{session_id}")])

    if current_path != "/":
        rows.append([InlineKeyboardButton("⬆️ 上一级", callback_data=f"dir:up:{session_id}")])

    entries: list[dict] = []
    if ok:
        for dirname in result:
            next_path = normalize_remote_path(f"{current_path.rstrip('/')}/{dirname}")
            entries.append({"type": "dir", "path": next_path})
            entry_id = str(len(entries) - 1)
            rows.append(
                [InlineKeyboardButton(f"📁 {dirname}", callback_data=f"dir:go:{session_id}:{entry_id}")]
            )
    else:
        rows.append([InlineKeyboardButton(f"⚠️ {result}", callback_data=f"dir:noop:{session_id}")])

    session = DIR_PICK_SESSIONS.get(session_id)
    if session is not None:
        _set_picker_entries(session, entries)

    rows.append([InlineKeyboardButton("❌ 取消", callback_data=f"dir:cancel:{session_id}")])
    return InlineKeyboardMarkup(rows)


def build_upload_dir_keyboard(session_id: str, current_path: str) -> InlineKeyboardMarkup:
    ok, result = list_openlist_dirs(current_path)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton("✅ 选择此目录", callback_data=f"up:pick:{session_id}")])

    if current_path != "/":
        rows.append([InlineKeyboardButton("⬆️ 上一级", callback_data=f"up:up:{session_id}")])

    entries: list[dict] = []
    if ok:
        for dirname in result:
            next_path = normalize_remote_path(f"{current_path.rstrip('/')}/{dirname}")
            entries.append({"type": "dir", "path": next_path})
            entry_id = str(len(entries) - 1)
            rows.append(
                [InlineKeyboardButton(f"📁 {dirname}", callback_data=f"up:go:{session_id}:{entry_id}")]
            )
    else:
        rows.append([InlineKeyboardButton(f"⚠️ {result}", callback_data=f"up:noop:{session_id}")])

    session = UPLOAD_PICK_SESSIONS.get(session_id)
    if session is not None:
        _set_picker_entries(session, entries)

    rows.append([InlineKeyboardButton("❌ 取消", callback_data=f"up:cancel:{session_id}")])
    return InlineKeyboardMarkup(rows)


def build_download_picker_keyboard(session_id: str, current_path: str) -> InlineKeyboardMarkup:
    ok, result = list_openlist_entries(current_path)
    rows: list[list[InlineKeyboardButton]] = []

    if current_path != "/":
        rows.append([InlineKeyboardButton("⬆️ 上一级", callback_data=f"dl:up:{session_id}")])

    entries: list[dict] = []
    if ok:
        dirs, files = result
        for dirname in dirs:
            next_path = normalize_remote_path(f"{current_path.rstrip('/')}/{dirname}")
            entries.append({"type": "dir", "path": next_path})
            entry_id = str(len(entries) - 1)
            rows.append(
                [InlineKeyboardButton(f"📁 {dirname}", callback_data=f"dl:go:{session_id}:{entry_id}")]
            )
        for filename in files:
            file_path = normalize_remote_path(f"{current_path.rstrip('/')}/{filename}")
            entries.append({"type": "file", "path": file_path})
            entry_id = str(len(entries) - 1)
            rows.append(
                [InlineKeyboardButton(f"📄 {filename}", callback_data=f"dl:file:{session_id}:{entry_id}")]
            )
    else:
        rows.append([InlineKeyboardButton(f"⚠️ {result}", callback_data=f"dl:noop:{session_id}")])

    session = DOWNLOAD_PICK_SESSIONS.get(session_id)
    if session is not None:
        _set_picker_entries(session, entries)

    rows.append([InlineKeyboardButton("❌ 取消", callback_data=f"dl:cancel:{session_id}")])
    return InlineKeyboardMarkup(rows)


def build_mkdir_dir_keyboard(session_id: str, current_path: str) -> InlineKeyboardMarkup:
    ok, result = list_openlist_dirs(current_path)
    rows: list[list[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton("✅ 选择此目录", callback_data=f"mk:pick:{session_id}")])

    if current_path != "/":
        rows.append([InlineKeyboardButton("⬆️ 上一级", callback_data=f"mk:up:{session_id}")])

    entries: list[dict] = []
    if ok:
        for dirname in result:
            next_path = normalize_remote_path(f"{current_path.rstrip('/')}/{dirname}")
            entries.append({"type": "dir", "path": next_path})
            entry_id = str(len(entries) - 1)
            rows.append(
                [InlineKeyboardButton(f"📁 {dirname}", callback_data=f"mk:go:{session_id}:{entry_id}")]
            )
    else:
        rows.append([InlineKeyboardButton(f"⚠️ {result}", callback_data=f"mk:noop:{session_id}")])

    session = MKDIR_PICK_SESSIONS.get(session_id)
    if session is not None:
        _set_picker_entries(session, entries)

    rows.append([InlineKeyboardButton("❌ 取消", callback_data=f"mk:cancel:{session_id}")])
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
    tool = task.get("tool")
    tool_prefix = f"[{tool}] " if tool else ""
    return f"- {tool_prefix}{name}\n  状态: {status} | 进度: {progress_text} | 速度: {speed}"


def list_openlist_tasks() -> tuple[bool, list[dict] | str]:
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

                if not resp.text.strip():
                    last_error = "响应为空"
                    continue

                try:
                    body = resp.json()
                except ValueError:
                    content_type = resp.headers.get("Content-Type", "")
                    snippet = resp.text[:200]
                    last_error = f"非JSON响应({content_type}): {snippet}"
                    continue

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


def list_qbit_tasks() -> tuple[bool, list[dict] | str]:
    if not QBIT_BASE_URL or not QBIT_USERNAME or not QBIT_PASSWORD:
        return False, "未配置 QBIT_BASE_URL/QBIT_USERNAME/QBIT_PASSWORD。"

    session = requests.Session()
    try:
        login_url = f"{QBIT_BASE_URL}/api/v2/auth/login"
        resp = session.post(
            login_url,
            data={"username": QBIT_USERNAME, "password": QBIT_PASSWORD},
            timeout=20,
        )
        if resp.status_code != 200 or resp.text.strip() != "Ok.":
            return False, f"登录失败，HTTP {resp.status_code}: {resp.text[:200]}"

        list_url = f"{QBIT_BASE_URL}/api/v2/torrents/info"
        resp = session.get(list_url, timeout=20)
        if resp.status_code != 200:
            return False, f"任务列表失败，HTTP {resp.status_code}: {resp.text[:200]}"

        torrents = resp.json()
        tasks: list[dict] = []
        for tor in torrents:
            tasks.append(
                {
                    "name": tor.get("name") or tor.get("hash") or "(未命名任务)",
                    "status": tor.get("state") or "unknown",
                    "progress": tor.get("progress"),
                    "speed": tor.get("dlspeed"),
                    "tool": "qb",
                }
            )
        return True, tasks
    except (requests.RequestException, ValueError) as exc:
        return False, f"查询失败: {exc}"
    finally:
        session.close()


def _aria2_rpc_call(method: str, params: list | None = None) -> tuple[bool, dict | list | str]:
    if not ARIA2_RPC_URL:
        return False, "未配置 ARIA2_RPC_URL。"

    payload: dict = {"jsonrpc": "2.0", "id": "bot", "method": method, "params": []}
    if params:
        payload["params"] = params
    if ARIA2_RPC_SECRET:
        payload["params"].insert(0, f"token:{ARIA2_RPC_SECRET}")

    try:
        resp = requests.post(ARIA2_RPC_URL, json=payload, timeout=20)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        if "error" in body:
            return False, body["error"].get("message", "未知错误")
        return True, body.get("result", [])
    except (requests.RequestException, ValueError) as exc:
        return False, str(exc)


def _aria2_extract_name(item: dict) -> str:
    if isinstance(item.get("bittorrent"), dict):
        info = item["bittorrent"].get("info", {})
        if isinstance(info, dict) and info.get("name"):
            return info["name"]
    files = item.get("files")
    if isinstance(files, list) and files:
        path = files[0].get("path")
        if path:
            return os.path.basename(path)
    return item.get("gid", "(未命名任务)")


def list_aria2_tasks() -> tuple[bool, list[dict] | str]:
    ok, active = _aria2_rpc_call(
        "aria2.tellActive",
        [[
            "gid",
            "status",
            "totalLength",
            "completedLength",
            "downloadSpeed",
            "files",
            "bittorrent",
        ]],
    )
    if not ok:
        return False, f"查询失败: {active}"

    ok_waiting, waiting = _aria2_rpc_call(
        "aria2.tellWaiting",
        [0, 20, [
            "gid",
            "status",
            "totalLength",
            "completedLength",
            "downloadSpeed",
            "files",
            "bittorrent",
        ]],
    )
    if not ok_waiting:
        waiting = []

    tasks: list[dict] = []
    for item in list(active) + list(waiting):
        total = float(item.get("totalLength") or 0)
        completed = float(item.get("completedLength") or 0)
        progress = completed / total if total > 0 else None
        tasks.append(
            {
                "name": _aria2_extract_name(item),
                "status": item.get("status") or "unknown",
                "progress": progress,
                "speed": item.get("downloadSpeed"),
                "tool": "aria2",
            }
        )

    return True, tasks


def list_offline_tasks_with_fallback() -> tuple[bool, tuple[str, list[dict]] | str]:
    ok, result = list_openlist_tasks()
    if ok and result:
        return True, ("OpenList", result)

    errors = [f"OpenList: {result}" if not ok else "OpenList: 无任务"]
    combined_tasks: list[dict] = []

    qb_ok, qb_result = list_qbit_tasks()
    if qb_ok:
        combined_tasks.extend(qb_result)
    else:
        errors.append(f"qBittorrent: {qb_result}")

    aria_ok, aria_result = list_aria2_tasks()
    if aria_ok:
        combined_tasks.extend(aria_result)
    else:
        errors.append(f"aria2: {aria_result}")

    if combined_tasks:
        return True, ("qBittorrent/aria2", combined_tasks)

    if ok:
        return True, ("OpenList", result)

    return False, "；".join(errors)


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    await update.message.reply_text("正在查询离线下载任务...")
    ok, result = list_offline_tasks_with_fallback()
    if not ok:
        await update.message.reply_text(str(result))
        return

    source, tasks = result
    if not tasks:
        await update.message.reply_text(f"{source} 当前没有离线下载任务。")
        return

    lines = [f"离线下载任务进度（来源: {source}，最多显示20条）:"]
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
        "/download - 打开文件选择器并下载文件\n"
        "/quick - 打开常用快捷操作菜单\n"
        "/mkdir - 选择父目录后输入文件夹名创建目录\n"
        "/setdir - 打开目录选择器并设置默认任务目录\n"
        "/getdir - 查看你当前默认任务目录\n"
        "/settool - 选择默认离线下载方式\n"
        "/gettool - 查看当前离线下载方式\n"
        "/upload - 打开目录选择器并等待上传\n"
        "/magnet <磁力链接> - 发送后弹出目录选择器\n"
        "/magnet <aria2|qb> <磁力链接> - 指定下载方式并选择目录\n"
        "/tasks - 查询离线下载任务进度\n\n"
        "上传方式:\n"
        "先发送 /upload 选择目录，再发送文档\n"
        "也可以直接发送 magnet:? 开头的磁力链接"
    )


async def quick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📄 下载文件", callback_data="quick:download")],
            [InlineKeyboardButton("📤 上传文件", callback_data="quick:upload")],
            [InlineKeyboardButton("📁 设置默认目录", callback_data="quick:setdir")],
            [InlineKeyboardButton("📂 创建目录", callback_data="quick:mkdir")],
            [InlineKeyboardButton("📍 查看当前目录", callback_data="quick:getdir")],
            [InlineKeyboardButton("🛠️ 设置离线方式", callback_data="quick:settool")],
            [InlineKeyboardButton("🧾 查看离线任务", callback_data="quick:tasks")],
            [InlineKeyboardButton("❌ 关闭菜单", callback_data="quick:cancel")],
        ]
    )
    await update.message.reply_text("请选择快捷操作：", reply_markup=keyboard)


async def setdir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    if not user:
        return
    await open_setdir_picker(user.id, update.message)


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
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("aria2", callback_data="settool:aria2")],
                [InlineKeyboardButton("qb", callback_data="settool:qb")],
                [InlineKeyboardButton("❌ 取消", callback_data="settool:cancel")],
            ]
        )
        await update.message.reply_text("请选择离线下载方式：", reply_markup=keyboard)
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

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    if not user:
        return
    await open_upload_picker(user.id, update.message)

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    if not user:
        return
    await open_download_picker(user.id, update.message)


async def mkdir(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    user = update.effective_user
    if not user:
        return
    await open_mkdir_picker(user.id, update.message)


def resolve_upload_path(upload_target: str, filename: str) -> str:
    upload_target = upload_target.strip()
    if upload_target.endswith("/"):
        return upload_target + filename
    if "." not in os.path.basename(upload_target):
        return upload_target.rstrip("/") + "/" + filename
    return upload_target


def create_offline_download_task(
    target_dir: str, magnet_link: str, offline_tool: str
) -> tuple[bool, str]:
    if not OPENLIST_API_URL or not OPENLIST_API_TOKEN:
        return False, "未配置 OPENLIST_API_URL 或 OPENLIST_API_TOKEN，无法创建离线下载任务。"

    api_url = build_openlist_api_url(OPENLIST_OFFLINE_ENDPOINT)
    normalized_target = normalize_remote_path(target_dir)
    headers = get_openlist_api_headers()
    tool = normalize_offline_tool(offline_tool)
    tool_variants = [tool]
    if tool == "qb":
        tool_variants.extend(["qbittorrent", "qbit"])
    elif tool == "aria2":
        tool_variants.extend(["aria2", "rpc"])

    base_payloads = [
        {"path": normalized_target, "urls": [magnet_link]},
        {"path": normalized_target, "url": magnet_link},
        {"dir": normalized_target, "url": magnet_link},
    ]

    payload_candidates: list[dict] = []
    for payload in base_payloads:
        payload_candidates.append(payload)
        for variant in tool_variants:
            payload_candidates.append({**payload, "tool": variant})
            payload_candidates.append({**payload, "method": variant})
            payload_candidates.append({**payload, "provider": variant})
            payload_candidates.append({**payload, "type": variant})

    last_error = ""
    for payload in payload_candidates:
        try:
            resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                continue

            if not resp.text.strip():
                last_error = "响应为空"
                continue

            try:
                body = resp.json()
            except ValueError:
                content_type = resp.headers.get("Content-Type", "")
                snippet = resp.text[:200]
                last_error = f"非JSON响应({content_type}): {snippet}"
                continue
            code = body.get("code")
            message = body.get("message", "")
            if code in (200, 0, None):
                return True, (
                    f"离线下载任务已创建到目录: {normalized_target}，方式: {tool}。"
                    "如果网页端未显示任务，请检查 OpenList 离线工具配置或用 /tasks 查询。"
                )

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


def create_folder_with_fallback(target_dir: str) -> tuple[bool, str]:
    ok, api_message = create_folder_by_api(target_dir)
    if ok:
        return True, api_message

    if not has_webdav_config():
        return False, (api_message or "未配置 WebDAV，且 API 创建目录失败。")

    parts = [p for p in target_dir.split("/") if p]
    current = ""
    try:
        for part in parts:
            current += f"/{part}"
            url = build_webdav_url(current + "/")
            resp = requests.request(
                "MKCOL", url, auth=(OPENLIST_USERNAME, OPENLIST_PASSWORD), timeout=30
            )
            if resp.status_code not in (201, 405):
                return False, f"创建目录失败: {current} (HTTP {resp.status_code})"
        return True, f"目录已就绪: {normalize_remote_path(target_dir)}"
    except requests.RequestException as exc:
        logger.exception("MKCOL failed")
        if api_message:
            return False, f"API 创建失败，回退 WebDAV 也失败: {api_message}; {exc}"
        return False, f"创建目录失败: {exc}"


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
            "/magnet <aria2|qb> <磁力链接>"
        )
        return

    default_tool = get_user_offline_tool(user.id)

    raw_first = context.args[0].strip().lower()
    inline_tool = None
    inline_args = context.args
    if raw_first in ("aria2", "qb", "qbit", "qbittorrent"):
        inline_tool = normalize_offline_tool(raw_first)
        inline_args = context.args[1:]

    magnet_link = next((arg for arg in inline_args if arg.startswith("magnet:?")), "")
    if not magnet_link:
        await update.message.reply_text(
            "用法:\n"
            "/magnet <磁力链接>\n"
            "/magnet <aria2|qb> <磁力链接>"
        )
        return

    default_target_dir = get_user_download_dir(user.id)
    session_id = next_magnet_session_id()
    chosen_tool = inline_tool or default_tool
    MAGNET_PICK_SESSIONS[session_id] = {
        "user_id": user.id,
        "magnet": magnet_link,
        "path": default_target_dir,
        "tool": chosen_tool,
    }
    keyboard = build_magnet_dir_keyboard(session_id, default_target_dir)
    await update.message.reply_text(
        f"请选择下载目录（当前: {default_target_dir}，方式: {chosen_tool}）",
        reply_markup=keyboard,
    )


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

    if action == "up":
        current_path = normalize_remote_path(str(session.get("path", "/")))
        new_path = os.path.dirname(current_path.rstrip("/")) or "/"
        session["path"] = new_path
        keyboard = build_magnet_dir_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择下载目录（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "go":
        resolved_path = _get_entry_path(session, extra)
        new_path = normalize_remote_path(resolved_path or extra or "/")
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


async def dir_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("dir:"):
        return

    parts = query.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    session = DIR_PICK_SESSIONS.get(session_id)
    if not session:
        await query.answer("会话已失效，请重新发送 /setdir", show_alert=True)
        return

    if int(session.get("user_id", -1)) != user.id:
        await query.answer("这个选择器不是你的。", show_alert=True)
        return

    if action == "noop":
        await query.answer("当前目录读取失败")
        return

    if action == "cancel":
        DIR_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text("已取消设置默认目录。")
        await query.answer()
        return

    if action == "up":
        current_path = normalize_remote_path(str(session.get("path", "/")))
        new_path = os.path.dirname(current_path.rstrip("/")) or "/"
        session["path"] = new_path
        keyboard = build_dir_picker_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择要设置的默认目录（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "go":
        resolved_path = _get_entry_path(session, extra)
        new_path = normalize_remote_path(resolved_path or extra or "/")
        session["path"] = new_path
        keyboard = build_dir_picker_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择要设置的默认目录（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "pick":
        target_dir = normalize_remote_path(str(session.get("path", "/")))
        DIR_PICK_SESSIONS.pop(session_id, None)
        USER_SELECTED_DIRS[user.id] = target_dir
        await query.edit_message_text(f"已设置默认目录: {target_dir}")
        await query.answer("已设置")
        return

    await query.answer("未知操作")


async def upload_dir_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("up:"):
        return

    parts = query.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    session = UPLOAD_PICK_SESSIONS.get(session_id)
    if not session:
        await query.answer("会话已失效，请重新发送 /upload", show_alert=True)
        return

    if int(session.get("user_id", -1)) != user.id:
        await query.answer("这个选择器不是你的。", show_alert=True)
        return

    if action == "noop":
        await query.answer("当前目录读取失败")
        return

    if action == "cancel":
        UPLOAD_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text("已取消选择上传目录。")
        await query.answer()
        return

    if action == "up":
        current_path = normalize_remote_path(str(session.get("path", "/")))
        new_path = os.path.dirname(current_path.rstrip("/")) or "/"
        session["path"] = new_path
        keyboard = build_upload_dir_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择上传目录（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "go":
        resolved_path = _get_entry_path(session, extra)
        new_path = normalize_remote_path(resolved_path or extra or "/")
        session["path"] = new_path
        keyboard = build_upload_dir_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择上传目录（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "pick":
        target_dir = normalize_remote_path(str(session.get("path", "/")))
        UPLOAD_PICK_SESSIONS.pop(session_id, None)
        USER_PENDING_UPLOAD_DIRS[user.id] = target_dir
        await query.edit_message_text(f"已选择上传目录: {target_dir}\n请发送要上传的文档。")
        await query.answer("已选择")
        return

    await query.answer("未知操作")


async def download_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("dl:"):
        return

    parts = query.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    session = DOWNLOAD_PICK_SESSIONS.get(session_id)
    if not session:
        await query.answer("会话已失效，请重新发送 /download", show_alert=True)
        return

    if int(session.get("user_id", -1)) != user.id:
        await query.answer("这个选择器不是你的。", show_alert=True)
        return

    if action == "noop":
        await query.answer("当前目录读取失败")
        return

    if action == "cancel":
        DOWNLOAD_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text("已取消下载。")
        await query.answer()
        return

    if action == "up":
        current_path = normalize_remote_path(str(session.get("path", "/")))
        new_path = os.path.dirname(current_path.rstrip("/")) or "/"
        session["path"] = new_path
        keyboard = build_download_picker_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择要下载的文件（当前目录: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "go":
        resolved_path = _get_entry_path(session, extra)
        new_path = normalize_remote_path(resolved_path or extra or "/")
        session["path"] = new_path
        keyboard = build_download_picker_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择要下载的文件（当前目录: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "file":
        resolved_path = _get_entry_path(session, extra)
        file_path = normalize_remote_path(resolved_path or extra or "/")
        DOWNLOAD_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text(f"开始下载: {file_path}")

        if not has_webdav_config():
            await query.message.reply_text(
                "未配置 OpenList WebDAV 账号密码（OPENLIST_WEBDAV_URL/OPENLIST_USERNAME/OPENLIST_PASSWORD），无法下载。"
            )
            await query.answer("缺少 WebDAV 配置", show_alert=True)
            return

        file_name = os.path.basename(file_path.rstrip("/")) or "download.bin"
        url = build_webdav_url(file_path)
        try:
            resp = requests.get(
                url,
                auth=(OPENLIST_USERNAME, OPENLIST_PASSWORD),
                stream=True,
                timeout=120,
            )
            if resp.status_code != 200:
                await query.message.reply_text(f"下载失败，HTTP {resp.status_code}")
                await query.answer("下载失败")
                return

            data = BytesIO(resp.content)
            data.name = file_name
            data.seek(0)
            await query.message.reply_document(document=data, filename=file_name)
            await query.answer("已下载")
        except requests.RequestException as exc:
            logger.exception("Download failed")
            await query.message.reply_text(f"下载失败: {exc}")
            await query.answer("下载失败")
        return

    await query.answer("未知操作")


async def mkdir_dir_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("mk:"):
        return

    parts = query.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    session_id = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""

    session = MKDIR_PICK_SESSIONS.get(session_id)
    if not session:
        await query.answer("会话已失效，请重新发送 /mkdir", show_alert=True)
        return

    if int(session.get("user_id", -1)) != user.id:
        await query.answer("这个选择器不是你的。", show_alert=True)
        return

    if action == "noop":
        await query.answer("当前目录读取失败")
        return

    if action == "cancel":
        MKDIR_PICK_SESSIONS.pop(session_id, None)
        await query.edit_message_text("已取消创建目录。")
        await query.answer()
        return

    if action == "up":
        current_path = normalize_remote_path(str(session.get("path", "/")))
        new_path = os.path.dirname(current_path.rstrip("/")) or "/"
        session["path"] = new_path
        keyboard = build_mkdir_dir_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择要创建目录的父路径（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "go":
        resolved_path = _get_entry_path(session, extra)
        new_path = normalize_remote_path(resolved_path or extra or "/")
        session["path"] = new_path
        keyboard = build_mkdir_dir_keyboard(session_id, new_path)
        await query.edit_message_text(
            f"请选择要创建目录的父路径（当前: {new_path}）",
            reply_markup=keyboard,
        )
        await query.answer()
        return

    if action == "pick":
        target_dir = normalize_remote_path(str(session.get("path", "/")))
        MKDIR_PICK_SESSIONS.pop(session_id, None)
        USER_PENDING_MKDIR_PARENTS[user.id] = target_dir
        await query.edit_message_text(f"已选择父目录: {target_dir}\n请发送要创建的文件夹名。")
        await query.answer("已选择")
        return

    await query.answer("未知操作")


async def quick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("quick:"):
        return

    action = query.data.split(":", 1)[1]
    message = query.message
    if message is None:
        await query.answer()
        return

    if action == "cancel":
        await query.edit_message_text("已关闭快捷菜单。")
        await query.answer()
        return

    if action == "download":
        await open_download_picker(user.id, message)
        await query.answer()
        return

    if action == "upload":
        await open_upload_picker(user.id, message)
        await query.answer()
        return

    if action == "setdir":
        await open_setdir_picker(user.id, message)
        await query.answer()
        return

    if action == "getdir":
        current_dir = get_user_download_dir(user.id)
        await message.reply_text(f"你当前默认目录: {current_dir}")
        await query.answer()
        return

    if action == "tasks":
        await message.reply_text("正在查询离线下载任务...")
        ok, result = list_offline_tasks_with_fallback()
        if not ok:
            await message.reply_text(str(result))
            await query.answer()
            return
        source, tasks = result
        if not tasks:
            await message.reply_text(f"{source} 当前没有离线下载任务。")
            await query.answer()
            return
        lines = [f"离线下载任务进度（来源: {source}，最多显示20条）:"]
        for task in tasks[:20]:
            lines.append(format_task_progress(task))
        await message.reply_text("\n".join(lines))
        await query.answer()
        return

    if action == "settool":
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("aria2", callback_data="settool:aria2")],
                [InlineKeyboardButton("qb", callback_data="settool:qb")],
                [InlineKeyboardButton("❌ 取消", callback_data="settool:cancel")],
            ]
        )
        await message.reply_text("请选择离线下载方式：", reply_markup=keyboard)
        await query.answer()
        return

    if action == "mkdir":
        await open_mkdir_picker(user.id, message)
        await query.answer()
        return

    await query.answer("未知操作")


async def settool_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    user = query.from_user
    if not is_allowed(user.id):
        await query.answer("没有权限", show_alert=True)
        return

    if not query.data.startswith("settool:"):
        return

    action = query.data.split(":", 1)[1]
    if action == "cancel":
        await query.edit_message_text("已取消设置离线下载方式。")
        await query.answer()
        return

    if action not in ("aria2", "qb"):
        await query.answer("无效选择", show_alert=True)
        return

    tool = normalize_offline_tool(action)
    USER_SELECTED_TOOLS[user.id] = tool
    await query.edit_message_text(f"已设置默认离线下载方式: {tool}")
    await query.answer("已设置")


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


async def mkdir_name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    msg = update.message
    if msg is None or not msg.text:
        return

    user = update.effective_user
    if not user:
        return

    parent_dir = USER_PENDING_MKDIR_PARENTS.pop(user.id, None)
    if not parent_dir:
        return

    text_value = msg.text.strip()
    if text_value.startswith("magnet:?"):
        await msg.reply_text(
            "你当前在创建目录流程中，请先发送文件夹名，或取消后再发磁力链接。"
        )
        return

    folder_name = text_value.strip("/")
    if not folder_name:
        await msg.reply_text("文件夹名不能为空，请重新发送名称。")
        return

    target = normalize_remote_path(f"{parent_dir.rstrip('/')}/{folder_name}")
    ok, message = create_folder_with_fallback(target)
    await msg.reply_text(message)


async def upload_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_auth(update):
        return

    msg = update.message
    if msg is None or msg.document is None:
        return

    pending_dir = USER_PENDING_UPLOAD_DIRS.pop(update.effective_user.id, None)
    if not pending_dir:
        await msg.reply_text("请先发送 /upload 选择上传目录，然后再发送文档。")
        return

    if not has_webdav_config():
        await msg.reply_text(
            "未配置 OpenList WebDAV 账号密码（OPENLIST_WEBDAV_URL/OPENLIST_USERNAME/OPENLIST_PASSWORD），无法上传。"
        )
        return

    remote_target = resolve_upload_path(pending_dir, msg.document.file_name)
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
    if not BOT_TOKEN:
        raise RuntimeError("缺少环境变量: TELEGRAM_BOT_TOKEN")


def main() -> None:
    validate_env()

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "显示帮助"),
                BotCommand("quick", "快捷操作菜单"),
                BotCommand("download", "打开选择器下载文件"),
                BotCommand("upload", "选择目录后上传文件"),
                BotCommand("mkdir", "选择目录后创建文件夹"),
                BotCommand("setdir", "选择默认下载目录"),
                BotCommand("getdir", "查看当前默认目录"),
                BotCommand("settool", "选择离线下载方式"),
                BotCommand("gettool", "查看离线下载方式"),
                BotCommand("magnet", "创建离线下载任务"),
                BotCommand("tasks", "查看离线任务"),
            ]
        )

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quick", quick_command))
    app.add_handler(CommandHandler("download", download_file))
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("mkdir", mkdir))
    app.add_handler(CommandHandler("setdir", setdir))
    app.add_handler(CommandHandler("getdir", getdir))
    app.add_handler(CommandHandler("settool", settool))
    app.add_handler(CommandHandler("gettool", gettool))
    app.add_handler(CommandHandler("magnet", magnet_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CallbackQueryHandler(magnet_dir_picker_callback, pattern=r"^mag:"))
    app.add_handler(CallbackQueryHandler(dir_picker_callback, pattern=r"^dir:"))
    app.add_handler(CallbackQueryHandler(upload_dir_picker_callback, pattern=r"^up:"))
    app.add_handler(CallbackQueryHandler(download_picker_callback, pattern=r"^dl:"))
    app.add_handler(CallbackQueryHandler(mkdir_dir_picker_callback, pattern=r"^mk:"))
    app.add_handler(CallbackQueryHandler(quick_callback, pattern=r"^quick:"))
    app.add_handler(CallbackQueryHandler(settool_callback, pattern=r"^settool:"))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mkdir_name_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, magnet_text_handler),
    )

    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
