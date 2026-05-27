#!/bin/bash
# 行为学训练盒 — 服务自检脚本
#
# 用法:
#   ./check.sh                  # 检查默认端口 8000
#   ./check.sh 8001             # 检查指定端口
#   ./manage.sh check           # 通过 manage.sh 调用
#
# 检查项:
#   1. 服务进程是否运行
#   2. HTTP GET / 返回 200
#   3. HTTP GET /api/experiments 返回 JSON + experiments 字段
#   4. 运行时数据目录 data_store/experiments/ 存在
#
# 全部 PASS → exit 0
# 任一 FAIL  → exit 1
#
# 修复指引:
#   [FAIL] 服务未运行   → ./manage.sh start 启动
#   [FAIL] API 异常     → 检查 server.py 是否有语法错误或未捕获异常
#   [FAIL] 数据路径不存在 → 检查 data_store/ 是否存在

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-8000}"
BASE_URL="http://localhost:${PORT}"

PASS=0
FAIL=0
RESULTS=""

check() {
  local name="$1"
  local status="$2"
  local hint="$3"
  if [ "$status" = "PASS" ]; then
    echo "[PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $name"
    echo "       → $hint"
    FAIL=$((FAIL + 1))
  fi
}

echo "══════════════════════════════════"
echo "  行为学训练盒 — 服务自检 (端口 ${PORT})"
echo "══════════════════════════════════"

# ── 检查项 1: 端口是否在监听 ──
if lsof -ti:"$PORT" 2>/dev/null | grep -q .; then
  check "服务运行中 (端口 ${PORT})" "PASS"
else
  check "服务运行中 (端口 ${PORT})" "FAIL" "请运行 ./manage.sh start ${PORT} 启动服务"
fi

# ── 检查项 2: HTTP GET / 返回 200 ──
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  check "HTTP GET / → ${HTTP_CODE}" "PASS"
else
  check "HTTP GET / → ${HTTP_CODE}" "FAIL" "服务未正确返回首页，检查 server.py 是否有语法错误"
fi

# ── 检查项 3: GET /api/experiments 返回 JSON + experiments 字段 ──
API_RESULT=$(curl -s "${BASE_URL}/api/experiments" 2>/dev/null)
if echo "$API_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'experiments' in d, 'missing experiments field'" 2>/dev/null; then
  check "GET /api/experiments → JSON + experiments 字段" "PASS"
else
  check "GET /api/experiments → JSON + experiments 字段" "FAIL" "API 返回异常或缺少 experiments 字段，检查 server.py 是否正常"
fi

# ── 检查项 4: data_store/experiments/ 目录存在 ──
if [ -d "${SCRIPT_DIR}/software/data_store/experiments" ]; then
  check "数据目录 data_store/experiments/ 存在" "PASS"
else
  check "数据目录 data_store/experiments/ 存在" "FAIL" "缺少 data_store/experiments/ 目录，请手动创建"
fi

# ── 结果汇总 ──
TOTAL=$((PASS + FAIL))
echo "────────────────────────────────"
echo "结果：${PASS}/${TOTAL} 通过"
echo "────────────────────────────────"

if [ "$FAIL" -gt 0 ]; then
  echo "请修复后重试"
  exit 1
else
  echo "全部通过，服务健康"
  exit 0
fi
