#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${TELEMETRY_STATE_DIR:-$HOME/.flightctrl}"
PID_FILE="${TELEMETRY_AGENT_PID:-$STATE_DIR/telemetry_agent.pid}"
LOG_FILE="${TELEMETRY_AGENT_LOG:-$ROOT_DIR/telemetry_agent.log}"
USE_SUDO="${TELEMETRY_AGENT_SUDO:-1}"
CMD=(env PYTHONPATH="$ROOT_DIR" python3 -m flightctrl_agent --backend "${TELEMETRY_BACKEND_URL:-http://127.0.0.1:8000}")

ensure_dir() {
  mkdir -p "$STATE_DIR"
}

pid_running() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

start_agent() {
  if pid_running; then
    echo "telemetry agent already running (pid $(cat "$PID_FILE"))"
    return 0
  fi
  ensure_dir
  if [[ "$USE_SUDO" == "1" ]]; then
    sudo -v
    nohup sudo -n "${CMD[@]}" > "$LOG_FILE" 2>&1 &
  else
    nohup "${CMD[@]}" > "$LOG_FILE" 2>&1 &
  fi
  echo $! > "$PID_FILE"
  disown || true
  echo "telemetry agent started (pid $(cat "$PID_FILE"))"
}

stop_agent() {
  if ! pid_running; then
    echo "telemetry agent not running"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  if [[ "$USE_SUDO" == "1" ]]; then
    sudo kill "$pid" 2>/dev/null || true
  else
    kill "$pid" 2>/dev/null || true
  fi
  for _ in {1..10}; do
    if kill -0 "$pid" 2>/dev/null; then
      sleep 0.2
    else
      break
    fi
  done
  if kill -0 "$pid" 2>/dev/null; then
    if [[ "$USE_SUDO" == "1" ]]; then
      sudo kill -9 "$pid" 2>/dev/null || true
    else
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PID_FILE"
  echo "telemetry agent stopped"
}

status_agent() {
  if pid_running; then
    echo "telemetry agent running (pid $(cat "$PID_FILE"))"
  else
    echo "telemetry agent stopped"
  fi
}

case "${1:-}" in
  start)
    start_agent
    ;;
  stop)
    stop_agent
    ;;
  restart)
    stop_agent
    start_agent
    ;;
  status)
    status_agent
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
