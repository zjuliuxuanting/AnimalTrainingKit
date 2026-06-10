#!/bin/bash
# 行为学训练盒 — 服务管理脚本
# 用法：
#   ./manage.sh start          # 启动服务（默认 8000）
#   ./manage.sh start 8001     # 指定端口启动
#   ./manage.sh stop           # 停止服务（默认 8000）
#   ./manage.sh stop 8001      # 停止指定端口
#   ./manage.sh restart        # 重启
#   ./manage.sh status         # 查看状态

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/software/logs"
mkdir -p "$LOG_DIR"

PORT="${2:-8000}"
PID_FILE="/tmp/behavior_box_${PORT}.pid"

SERVER_PY="$PROJECT_ROOT/software/server.py"

case "$1" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "服务已在端口 $PORT 运行中 (PID: $(cat "$PID_FILE"))"
      exit 0
    fi
    rm -f "$PID_FILE"
    cd "$PROJECT_ROOT"
    nohup python3 "$SERVER_PY" --port "$PORT" \
      > "$LOG_DIR/server_${PORT}.log" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
      echo "✅ 服务已启动 → http://localhost:${PORT} (PID: $PID)"
    else
      echo "❌ 启动失败，查看日志: $LOG_DIR/server_${PORT}.log"
      rm -f "$PID_FILE"
    fi
    ;;
  stop)
    if [ ! -f "$PID_FILE" ]; then
      echo "没有找到端口 $PORT 的服务 PID 文件"
      # 尝试 lsof 找
      PID=$(lsof -ti:"$PORT" 2>/dev/null)
      if [ -n "$PID" ]; then
        echo "发现残留进程 PID: $PID，正在停止..."
        kill "$PID" 2>/dev/null
        sleep 1
        echo "✅ 已停止"
      fi
      exit 0
    fi
    PID=$(cat "$PID_FILE")
    kill "$PID" 2>/dev/null
    sleep 1
    rm -f "$PID_FILE"
    echo "✅ 端口 $PORT 服务已停止"
    ;;
  restart)
    "$0" stop "$PORT"
    sleep 1
    "$0" start "$PORT"
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      PID=$(cat "$PID_FILE")
      echo "✅ 端口 $PORT 服务运行中 (PID: $PID)"
      curl -s "http://localhost:${PORT}/api/status" 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  API 暂未响应"
    else
      # 尝试 lsof
      PID=$(lsof -ti:"$PORT" 2>/dev/null)
      if [ -n "$PID" ]; then
        echo "⚠️  端口 $PORT 被占用 (PID: $PID)，但非本脚本管理"
      else
        echo "❌ 端口 $PORT 没有服务运行"
      fi
    fi
    ;;
  check)
    "$SCRIPT_DIR/check.sh" "$PORT"
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status|check} [端口]"
    echo "示例: $0 start        # 启动 8000"
    echo "      $0 start 8080   # 启动 8080"
    echo "      $0 stop         # 停止 8000"
    echo "      $0 check        # 自检 8000"
    exit 1
    ;;
esac
