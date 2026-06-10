#!/bin/bash
# 行为学训练盒 — 工作区审计脚本
#
# 目标：
#   1. 让非软件工程背景的协作者快速看懂“为什么 git 变脏”
#   2. 把变更分成：真实代码 / 运行产物 / 历史遗留跟踪物
#   3. 帮助提交时拆分“功能提交”和“清理提交”
#
# 用法：
#   ./scripts/audit_worktree.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

print_section() {
  echo
  echo "══════════════════════════════════"
  echo "  $1"
  echo "══════════════════════════════════"
}

print_matches() {
  local title="$1"
  local pattern="$2"
  local source_cmd="$3"
  local matched
  matched=$(eval "$source_cmd" | rg "$pattern" || true)
  echo "[$title]"
  if [ -n "$matched" ]; then
    echo "$matched"
  else
    echo "(none)"
  fi
  echo
}

STATUS_CMD="git status --short"
TRACKED_CMD="git ls-files"

print_section "工作区摘要"
git status --short --branch

print_section "版本边界"
cat <<'EOF'
[应纳入版本控制]
- software/*.py
- software/session/ software/protocol/ software/web/ software/tests/
- software/e2e/
- scripts/
- package.json package-lock.json playwright.config.js skills-lock.json
- AGENTS.md
- 项目/07_会议与沟通/测试报告.md
- 项目/07_会议与沟通/软件进展报告.md

[本地运行产物，不应进入版本库]
- software/data_store/
- software/package.json software/package-lock.json software/playwright.config.js
- node_modules/ .playwright-mcp/
- software/node_modules/
- playwright-report/ test-results/
- e2e/playwright-report/ e2e/test-results/
- software/test_pw_*.png software/test_pw_page*.html

[历史上曾被错误纳入版本库，正在等待清退]
- 根目录 node_modules/ .playwright-mcp/
- 根目录 e2e/
- .playwright-mcp/
- software/data_store/experiments/*.json
- docs/项目总结PPT.html
EOF

print_section "本次真实代码改动"
print_matches \
  "代码与测试" \
  '^( M|M |A |AM|MM|R |\?\?) (software/(server\.py|session/.*|web/.*|tests/.*|e2e/.*|data/quota_state\.py|test_chains\.py)|package\.json|package-lock\.json|playwright\.config\.js|skills-lock\.json|AGENTS\.md|项目/07_会议与沟通/(测试报告|软件进展报告)\.md|\.gitignore|README\.md|scripts/(audit_worktree|manage)\.sh)$' \
  "$STATUS_CMD"

print_section "本次运行产物改动"
print_matches \
  "运行数据与本地产物" \
  '^( M|M |A |AM|MM|R |\?\?) "?(software/data_store/.*|software/node_modules/.*|software/playwright-report/.*|software/test-results/.*|software/test_pw_.*|software/test_pw_page.*|software/project-dashboard\.html)' \
  "$STATUS_CMD"

print_section "等待清退的历史遗留跟踪物"
print_matches \
  "已被跟踪但应退出版本库" \
  '^(\.playwright-mcp/|node_modules/|e2e/|software/data_store/experiments/.*flow\.json$|docs/项目总结PPT\.html$)' \
  "$TRACKED_CMD"

print_section "建议动作"
cat <<'EOF'
1. 功能提交只包含真实代码改动，不混入 data_store、node_modules、截图。
2. 清理历史遗留时，单独做一次 cleanup 提交，不和功能提交混在一起。
3. 如果要确认某个文件该不该提交，先跑本脚本，再看 README 里的“版本产物归属”。
EOF
