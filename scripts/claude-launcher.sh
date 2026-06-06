#!/bin/bash
# Claude Code 多模型启动器
# 双击运行，选择要使用的模型

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEEPSEEK_KEY="${DEEPSEEK_KEY:-}"

# ── 颜色 ──────────────────────────────────────────────
CYAN='\033[0;36m'
NC='\033[0m'

# ── 端口 ────────────────────────────────────────────
DASH_PORT=8100

# ── 检查端口是否占用 ────────────────────────────────
port_used() { lsof -i ":$1" >/dev/null 2>&1; }

# ── 清理后台进程 ──────────────────────────────────────
cleanup() {
  echo ""
  echo "🛑 清理后台服务..."
  lsof -ti :8090 2>/dev/null | xargs kill 2>/dev/null
  lsof -ti :$DASH_PORT 2>/dev/null | xargs kill 2>/dev/null
  echo "✅ 已清理"
}
trap cleanup EXIT

# ── 选择会话模式 ──────────────────────────────────────
select_session_mode() {
  echo "" >&2
  echo "  会话模式：" >&2
  echo "  ${CYAN}r${NC}) Resume  ↩️   恢复上次会话" >&2
  echo "  ${CYAN}n${NC}) New     🆕   新建会话" >&2
  echo "" >&2
  echo -n "  输入 (r/n) > " >&2
  read -r MODE
  if [ "$MODE" = "r" ] || [ "$MODE" = "R" ]; then
    echo " -r"
  else
    echo ""
  fi
}

# ── 主菜单 ────────────────────────────────────────────
clear
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║       Claude Code 多模型启动器          ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "请选择模型："
echo ""
echo "  ${CYAN}1${NC}) Qwen 本地  🖥️   (llama.cpp + qwen35b)"
echo "  ${CYAN}2${NC}) Qwen 远程  ☁️    (NAS 192.168.31.236)"
echo "  ${CYAN}3${NC}) DeepSeek   🌐   (V4 API 直连)"
echo "  ${CYAN}4${NC}) Claude     🔵   (官方 API)"
echo "  ${CYAN}5${NC}) Token Monitor 📊  (浏览器看板)"
echo ""
echo -n "输入编号 (1-5) > "
read -r CHOICE

case "$CHOICE" in
  1)
    # ── Qwen 本地 ──────────────────────────────────────
    LLAMA_PORT=8899
    PROXY_PORT=8900
    SESSION_FLAG=$(select_session_mode)

    # 启动 llama.cpp
    bash "$SCRIPT_DIR/start-llama.sh" || exit 1

    # 启动 proxy
    if ! port_used "$PROXY_PORT"; then
      echo "[+] 启动 Anthropic 适配器 (${PROXY_PORT} → ${LLAMA_PORT})..."
      node "$SCRIPT_DIR/qwen-local.mjs" &
      PROXY_PID=$!
      sleep 2
      echo "    ✅ 适配器就绪"
    else
      echo "[+] 适配器已运行 (port $PROXY_PORT)"
    fi

    echo ""
    echo "──────────────────────────────────────────"
    echo "  🚀 启动 Claude Code (Qwen 本地)"
    echo "──────────────────────────────────────────"
    echo ""
    claude --settings "$HOME/.claude/settings-qwen-local.json" --dangerously-skip-permissions $SESSION_FLAG
    ;;

  2)
    # ── Qwen 远程 (NAS) ─────────────────────────────
    UPSTREAM="http://192.168.31.236:8080"
    PROXY_PORT=8090
    SESSION_FLAG=$(select_session_mode)

    # 检查 NAS 是否在线
    echo ""
    echo -n "[ ] 检查远程服务器 $UPSTREAM ... "
    if curl -sf "$UPSTREAM/health" > /dev/null 2>&1; then
      echo "✅ 在线"
    else
      echo "❌ 无法连接"
      echo "请确保 NAS 上的 llama.cpp 已启动"
      echo ""
      echo "按 Enter 退出..."
      read -r
      exit 1
    fi

    # 启动 claude-adapter（Anthropic ↔ OpenAI 协议转换）
    if ! port_used "$PROXY_PORT"; then
      echo "[+] 启动 claude-adapter (${PROXY_PORT} → NAS ${UPSTREAM})..."
      npx claude-adapter --no-claude-settings -p "$PROXY_PORT" &>/tmp/claude-adapter.log &
      sleep 3
      echo "    ✅ 适配器就绪"
    else
      echo "[+] claude-adapter 已运行 (port $PROXY_PORT)"
    fi

    echo ""
    echo "──────────────────────────────────────────"
    echo "  🚀 启动 Claude Code (Qwen 远程)"
    echo "──────────────────────────────────────────"
    echo ""
    claude --settings "$HOME/.claude/settings-local.json" --dangerously-skip-permissions $SESSION_FLAG
    ;;

  3)
    # ── DeepSeek V4 ──────────────────────────────────
    SESSION_FLAG=$(select_session_mode)
    echo ""
    echo "──────────────────────────────────────────"
    echo "  🚀 启动 Claude Code (DeepSeek V4)"
    echo "──────────────────────────────────────────"
    echo ""
    ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic \
    ANTHROPIC_AUTH_TOKEN=$DEEPSEEK_KEY \
    ANTHROPIC_MODEL='claude-opus[1m]' \
    ANTHROPIC_DEFAULT_OPUS_MODEL='deepseek-v4-pro' \
    ANTHROPIC_DEFAULT_SONNET_MODEL='deepseek-v4-pro' \
    ANTHROPIC_DEFAULT_HAIKU_MODEL='deepseek-v4-flash' \
    CLAUDE_CODE_SUBAGENT_MODEL='deepseek-v4-flash' \
    claude $SESSION_FLAG
    ;;

  4)
    # ── Claude 官方 ─────────────────────────────────
    SESSION_FLAG=$(select_session_mode)
    echo ""
    echo "──────────────────────────────────────────"
    echo "  🚀 启动 Claude Code (官方 API)"
    echo "──────────────────────────────────────────"
    echo ""
    claude $SESSION_FLAG
    ;;

  5)
    # ── Token Monitor Dashboard ─────────────────────
    DASH_DIR="$(cd "$(dirname "$0")" && pwd)/token-dashboard"

    if ! port_used "$DASH_PORT"; then
      echo ""
      echo "[+] 启动 Token Monitor (http://localhost:${DASH_PORT})..."
      python3 "$DASH_DIR/server.py" &
      DASH_PID=$!
      sleep 1
      echo "    ✅ 就绪"
    else
      echo "[+] Token Monitor 已运行"
    fi

    open "http://localhost:${DASH_PORT}"
    echo ""
    echo "按 Enter 关闭 Token Monitor 并退出..."
    read -r
    lsof -ti :"$DASH_PORT" 2>/dev/null | xargs kill 2>/dev/null
    ;;

  *)
    echo "无效输入"
    echo ""
    echo "按 Enter 退出..."
    read -r
    exit 1
    ;;
esac

echo ""
echo "Claude Code 已退出。"
echo "按 Enter 关闭..."
read -r
