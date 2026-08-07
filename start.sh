#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
BACKEND_PORT="${BACKEND_PORT:-8900}"
FRONTEND_PORT="${FRONTEND_PORT:-5178}"
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
BACKEND_STARTED=0
FRONTEND_STARTED=0
CLEANUP_DONE=0

mkdir -p "$RUN_DIR"

info() { printf '\033[1;34m[信息]\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m[完成]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[提示]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }

http_ok() {
  curl -fsS --connect-timeout 1 --max-time 5 "$1" >/dev/null 2>&1
}

pid_is_owned() {
  local pid_file="$1"
  local expected_dir="$2"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1

  # PID may have been reused. Only manage a process whose working directory
  # belongs to this project.
  if command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | grep -Fxq "n$expected_dir"
    return
  fi
  return 0
}

clear_stale_pid() {
  local pid_file="$1"
  local expected_dir="$2"
  if [[ -f "$pid_file" ]] && ! pid_is_owned "$pid_file" "$expected_dir"; then
    rm -f "$pid_file"
  fi
}

port_owner() {
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1
}

wait_for_url() {
  local url="$1"
  local seconds="${2:-30}"
  local count=0
  until http_ok "$url"; do
    sleep 1
    count=$((count + 1))
    (( count < seconds )) || return 1
  done
}

prepare_backend() {
  if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    return
  fi
  info "首次运行：安装后端依赖"
  if command -v uv >/dev/null 2>&1; then
    (cd "$BACKEND_DIR" && uv sync --extra dev)
  else
    command -v python3 >/dev/null 2>&1 || fail "未找到 Python 3，请先安装 Python 3.11 或更高版本"
    python3 -m venv "$BACKEND_DIR/.venv"
    "$BACKEND_DIR/.venv/bin/python" -m pip install -e "$BACKEND_DIR[dev]"
  fi
}

prepare_frontend() {
  if [[ -x "$FRONTEND_DIR/node_modules/.bin/vite" ]] &&
    (cd "$FRONTEND_DIR" && node -e "require('./node_modules/rollup/dist/native.js')" >/dev/null 2>&1); then
    return
  fi
  command -v npm >/dev/null 2>&1 || fail "未找到 npm，请先安装 Node.js"
  if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
    warn "当前 Node 架构缺少 Rollup 原生依赖，正在自动修复"
  else
    info "首次运行：安装前端依赖"
  fi
  (cd "$FRONTEND_DIR" && npm install --include=optional)
  (cd "$FRONTEND_DIR" && node -e "require('./node_modules/rollup/dist/native.js')" >/dev/null 2>&1) ||
    fail "Rollup 原生依赖安装失败，请查看 npm 输出"
}

start_backend() {
  clear_stale_pid "$BACKEND_PID_FILE" "$BACKEND_DIR"
  if http_ok "$BACKEND_URL/api/dashboard"; then
    ok "后端已在运行：$BACKEND_URL"
    return 1
  fi
  local owner
  owner="$(port_owner "$BACKEND_PORT" || true)"
  [[ -z "$owner" ]] || fail "后端端口 $BACKEND_PORT 已被进程 $owner 占用"

  info "启动后端服务"
  (cd "$BACKEND_DIR" && exec ./.venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 --port "$BACKEND_PORT") >"$BACKEND_LOG" 2>&1 &
  printf '%s\n' "$!" >"$BACKEND_PID_FILE"
  BACKEND_STARTED=1
  if ! wait_for_url "$BACKEND_URL/api/dashboard"; then
    tail -30 "$BACKEND_LOG" >&2 || true
    return 1
  fi
  ok "后端启动成功：$BACKEND_URL"
  return 0
}

start_frontend() {
  clear_stale_pid "$FRONTEND_PID_FILE" "$FRONTEND_DIR"
  if http_ok "$FRONTEND_URL"; then
    ok "前端已在运行：$FRONTEND_URL"
    return 1
  fi
  local owner
  owner="$(port_owner "$FRONTEND_PORT" || true)"
  [[ -z "$owner" ]] || fail "前端端口 $FRONTEND_PORT 已被进程 $owner 占用"

  info "启动前端服务"
  (cd "$FRONTEND_DIR" && exec ./node_modules/.bin/vite --host 127.0.0.1 \
    --port "$FRONTEND_PORT" --strictPort) >"$FRONTEND_LOG" 2>&1 &
  printf '%s\n' "$!" >"$FRONTEND_PID_FILE"
  FRONTEND_STARTED=1
  if ! wait_for_url "$FRONTEND_URL"; then
    tail -30 "$FRONTEND_LOG" >&2 || true
    return 1
  fi
  ok "前端启动成功：$FRONTEND_URL"
  return 0
}

stop_service() {
  local name="$1"
  local pid_file="$2"
  local expected_dir="$3"
  if ! pid_is_owned "$pid_file" "$expected_dir"; then
    rm -f "$pid_file"
    warn "$name 未由本脚本运行或已经停止"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  info "停止${name}（PID ${pid}）"
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
  ok "${name}已停止"
}

cleanup_started_services() {
  (( CLEANUP_DONE == 0 )) || return
  CLEANUP_DONE=1

  if (( FRONTEND_STARTED == 1 )); then
    stop_service "前端" "$FRONTEND_PID_FILE" "$FRONTEND_DIR"
  fi
  if (( BACKEND_STARTED == 1 )); then
    stop_service "后端" "$BACKEND_PID_FILE" "$BACKEND_DIR"
  fi
}

handle_exit_signal() {
  printf '\n'
  warn "收到退出信号，正在清理仿真服务"
  exit 0
}

supervise_services() {
  info "服务由当前终端监督；按 Ctrl+C 可完整停止"
  while true; do
    if (( BACKEND_STARTED == 1 )) && ! pid_is_owned "$BACKEND_PID_FILE" "$BACKEND_DIR"; then
      warn "后端进程意外退出，正在停止其余服务；日志：$BACKEND_LOG"
      return 1
    fi
    if (( FRONTEND_STARTED == 1 )) && ! pid_is_owned "$FRONTEND_PID_FILE" "$FRONTEND_DIR"; then
      warn "前端进程意外退出，正在停止其余服务；日志：$FRONTEND_LOG"
      return 1
    fi
    sleep 1
  done
}

show_status() {
  if http_ok "$BACKEND_URL/api/dashboard"; then
    ok "后端运行中：$BACKEND_URL"
  else
    warn "后端未运行"
  fi
  if http_ok "$FRONTEND_URL"; then
    ok "前端运行中：$FRONTEND_URL"
  else
    warn "前端未运行"
  fi
}

start_all() {
  trap cleanup_started_services EXIT
  trap handle_exit_signal INT TERM HUP
  prepare_backend
  prepare_frontend
  if ! start_backend && (( BACKEND_STARTED == 1 )); then
    fail "后端启动失败，完整日志：$BACKEND_LOG"
  fi
  if ! start_frontend && (( FRONTEND_STARTED == 1 )); then
    fail "前端启动失败，完整日志：$FRONTEND_LOG"
  fi
  printf '\n'
  show_status
  printf '\n访问地址：%s\n' "$FRONTEND_URL"
  if [[ "${NO_OPEN:-0}" != "1" ]] && command -v open >/dev/null 2>&1; then
    open "$FRONTEND_URL"
  fi
  if (( BACKEND_STARTED == 1 || FRONTEND_STARTED == 1 )); then
    supervise_services
  else
    warn "服务已由其他进程运行，本次未接管进程监督"
  fi
}

case "${1:-start}" in
  start) start_all ;;
  stop)
    stop_service "前端" "$FRONTEND_PID_FILE" "$FRONTEND_DIR"
    stop_service "后端" "$BACKEND_PID_FILE" "$BACKEND_DIR"
    ;;
  restart)
    stop_service "前端" "$FRONTEND_PID_FILE" "$FRONTEND_DIR"
    stop_service "后端" "$BACKEND_PID_FILE" "$BACKEND_DIR"
    start_all
    ;;
  status) show_status ;;
  *)
    printf '用法：%s [start|stop|restart|status]\n' "$0"
    exit 2
    ;;
esac
