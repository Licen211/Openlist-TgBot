#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"
BOT_FILE="$PROJECT_DIR/bot.py"
REQ_FILE="$PROJECT_DIR/requirements.txt"
PID_FILE="$PROJECT_DIR/.bot.pid"
LOG_FILE="$PROJECT_DIR/bot.log"

cd "$PROJECT_DIR"

print_header() {
  echo "========================================"
  echo " OpenList-TgBot 一键安装与管理菜单"
  echo "========================================"
}

ensure_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "已创建 .env，请先在菜单中配置密钥。"
  fi
}

install_deps() {
  echo "[1/4] 创建虚拟环境..."
  python3 -m venv "$VENV_DIR"

  echo "[2/4] 安装依赖..."
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r "$REQ_FILE"

  echo "[3/4] 初始化配置文件..."
  ensure_env_file

  echo "[4/4] 安装完成。"
}

set_env_value() {
  local key="$1"
  local value="$2"

  if grep -qE "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

configure_env_interactive() {
  ensure_env_file
  echo "\n请输入以下配置（直接回车可保持当前值）："

  local keys=(
    TELEGRAM_BOT_TOKEN
    ALLOWED_USER_IDS
    OPENLIST_WEBDAV_URL
    OPENLIST_USERNAME
    OPENLIST_PASSWORD
    OPENLIST_API_URL
    OPENLIST_API_TOKEN
    OPENLIST_OFFLINE_ENDPOINT
    OPENLIST_MKDIR_ENDPOINT
    OPENLIST_LIST_ENDPOINT
    OPENLIST_OFFLINE_LIST_ENDPOINT
    OPENLIST_DEFAULT_DOWNLOAD_DIR
    OPENLIST_DEFAULT_OFFLINE_TOOL
  )

  for key in "${keys[@]}"; do
    local current
    current="$(grep -E "^${key}=" "$ENV_FILE" | head -n1 | cut -d'=' -f2- || true)"

    if [[ "$key" == *"PASSWORD" || "$key" == *"TOKEN" ]]; then
      read -r -s -p "${key} [当前已设置隐藏，直接回车保持]: " input
      echo
      if [[ -n "${input}" ]]; then
        set_env_value "$key" "$input"
      fi
    else
      read -r -p "${key} [${current:-未设置}]: " input
      if [[ -n "${input}" ]]; then
        set_env_value "$key" "$input"
      fi
    fi
  done

  echo "配置已更新：$ENV_FILE"
}

show_env_masked() {
  ensure_env_file
  echo "\n当前配置（敏感字段已脱敏）："
  while IFS='=' read -r key value; do
    [[ -z "$key" ]] && continue
    if [[ "$key" == *"PASSWORD" || "$key" == *"TOKEN" ]]; then
      if [[ -n "$value" ]]; then
        echo "$key=******"
      else
        echo "$key="
      fi
    else
      echo "$key=$value"
    fi
  done < <(grep -E '^[A-Z0-9_]+=' "$ENV_FILE" || true)
}

is_running() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

start_bot() {
  ensure_env_file

  if is_running; then
    echo "机器人已在运行，PID: $(cat "$PID_FILE")"
    return
  fi

  echo "启动机器人..."
  nohup "$VENV_DIR/bin/python" "$BOT_FILE" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1

  if is_running; then
    echo "启动成功，PID: $(cat "$PID_FILE")"
    echo "日志文件: $LOG_FILE"
  else
    echo "启动失败，请检查日志: $LOG_FILE"
    rm -f "$PID_FILE"
  fi
}

stop_bot() {
  if ! is_running; then
    echo "机器人未运行。"
    rm -f "$PID_FILE"
    return
  fi

  local pid
  pid="$(cat "$PID_FILE")"
  echo "停止机器人，PID: $pid"
  kill "$pid" || true
  sleep 1

  if kill -0 "$pid" 2>/dev/null; then
    echo "进程仍在运行，执行强制停止..."
    kill -9 "$pid" || true
  fi

  rm -f "$PID_FILE"
  echo "已停止。"
}

status_bot() {
  if is_running; then
    echo "运行中，PID: $(cat "$PID_FILE")"
  else
    echo "未运行"
  fi
}

view_log() {
  if [[ ! -f "$LOG_FILE" ]]; then
    echo "暂无日志文件。"
    return
  fi
  tail -n 50 "$LOG_FILE"
}

quick_install_and_start() {
  install_deps
  configure_env_interactive
  start_bot
}

menu() {
  while true; do
    print_header
    echo "1) 一键安装并启动"
    echo "2) 安装/更新依赖"
    echo "3) 配置密钥和参数"
    echo "4) 查看当前配置（脱敏）"
    echo "5) 启动机器人"
    echo "6) 停止机器人"
    echo "7) 查看运行状态"
    echo "8) 查看最近日志"
    echo "0) 退出"
    read -r -p "请选择: " choice

    case "$choice" in
      1) quick_install_and_start ;;
      2) install_deps ;;
      3) configure_env_interactive ;;
      4) show_env_masked ;;
      5) start_bot ;;
      6) stop_bot ;;
      7) status_bot ;;
      8) view_log ;;
      0) echo "已退出"; break ;;
      *) echo "无效选项" ;;
    esac

    echo
    read -r -p "按回车继续..." _
    clear || true
  done
}

if [[ ! -f "$REQ_FILE" || ! -f "$BOT_FILE" ]]; then
  echo "请在项目根目录执行本脚本。"
  exit 1
fi

menu
