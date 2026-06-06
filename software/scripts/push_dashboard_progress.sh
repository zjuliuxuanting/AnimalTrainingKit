#!/bin/bash
# 端口规范v2 进度推送脚本
# 每5分钟更新一次 dashboard_today_summary.json，持续1小时
# 用法: bash scripts/push_dashboard_progress.sh

SUMMARY_FILE="/Applications/test/创业/行为学盒项目/behavior_box/software/data_store/dashboard_today_summary.json"
MEMORY_FILE="/Users/qingting/WorkBuddy/2026-06-06-15-45-26/.workbuddy/memory/2026-06-06.md"
BOARD_MAIN="/Applications/test/创业/行为学盒项目/behavior_box/项目/01_阶段规划/推进看板.md"
BOARD_SOFTWARE="/Applications/test/创业/行为学盒项目/behavior_box/项目/01_阶段规划/软件推进看板.md"
START_TIME=$(date +%s)
END_TIME=$((START_TIME + 3600))
COUNTER=0

echo "🔄 端口规范v2进度推送 启动 @ $(date '+%H:%M')"
echo "   持续至 $(date -r $END_TIME '+%H:%M')，共12次推送"

mkdir -p "$(dirname "$MEMORY_FILE")"

while [ $(date +%s) -lt $END_TIME ]; do
  COUNTER=$((COUNTER + 1))
  NOW=$(date '+%Y-%m-%d %H:%M:%S')
  NOW_SHORT=$(date '+%H:%M')
  
  echo ""
  echo "=== 第 $COUNTER 次推送 @ $NOW ==="
  
  # 检查服务器状态
  SERVER_STATUS="离线"
  if curl -s --max-time 3 http://localhost:8000/api/dashboard/data > /dev/null 2>&1; then
    SERVER_STATUS="在线"
    echo "  ✅ 服务器在线"
  else
    echo "  ⏳ 服务器离线"
  fi
  
  # 更新 JSON 文件
  if [ -f "$SUMMARY_FILE" ]; then
    # 用 Python 更新 JSON
    python3 -c "
import json, datetime

with open('$SUMMARY_FILE', 'r', encoding='utf-8') as f:
    data = json.load(f)

data['last_updated'] = '$NOW'
data['refresh_count'] = data.get('refresh_count', 0) + 1
data['most_recent_activity'] = '🔄 第${COUNTER}次自动刷新 @ $NOW_SHORT — 服务端: $SERVER_STATUS'

# 在第3次和第8次追加时间线记录
rc = data['refresh_count']
if rc == 3 or rc == 8:
    if 'updates' not in data:
        data['updates'] = []
    data['updates'].append({
        'time': '$NOW_SHORT',
        'content': '🔄 定时刷新 #${COUNTER} — 端口规范v2签字进行中',
        'detail': '服务端: $SERVER_STATUS'
    })

with open('$SUMMARY_FILE', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('  ✅ 今日总结已更新')
"
  else
    echo "  ❌ JSON 文件不存在"
  fi
  
  # 写 memory
  MEMO_LINE="- [自动化] 端口规范v2进度推送 第${COUNTER}次刷新 @ $NOW_SHORT — 服务器: $SERVER_STATUS"
  if [ ! -f "$MEMORY_FILE" ]; then
    echo "# 2026-06-06 工作记录" > "$MEMORY_FILE"
    echo "" >> "$MEMORY_FILE"
    echo "## 自动化进度推送" >> "$MEMORY_FILE"
  fi
  echo "$MEMO_LINE" >> "$MEMORY_FILE"
  echo "  ✅ Memory 已记录"
  
  # 更新推进面板
  python3 -c "
import re
from datetime import datetime

now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
today = datetime.now().strftime('%Y-%m-%d')

# === 推进看板.md ===
board_main = '$BOARD_MAIN'
try:
    with open(board_main, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 更新最后更新日期
    content = re.sub(r'最后更新：[0-9]{4}-[0-9]{2}-[0-9]{2}', f'最后更新：{today}', content)
    
    # 更新「此刻」表中创始人行
    old_founder = r'\|\*\*你（创始人）\*\*.*?\|.*?\|.*?\|'
    new_founder = f'| **你（创始人）** | 🗣 端口规范v2 签字会议（4条决定已定，记录事件注册讨论中） | 🔄 活跃 |'
    content = re.sub(old_founder, new_founder, content)
    
    # 更新「你今天要做」任务列表（仅更新最后更新日期，不改变任务列表内容）
    # 替换卡在哪里的日期参考（如果有）
    
    with open(board_main, 'w', encoding='utf-8') as f:
        f.write(content)
    print('  ✅ 推进看板.md 已更新')
except Exception as e:
    print(f'  ⚠️ 推进看板.md 更新失败: {e}')

# === 软件推进看板.md ===
board_sw = '$BOARD_SOFTWARE'
try:
    with open(board_sw, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 更新最后更新日期
    content = re.sub(r'最后更新：[0-9]{4}-[0-9]{2}-[0-9]{2}', f'最后更新：{today}', content)
    
    # 更新「此刻谁在做什么」表中创始人行
    old_founder_sw = r'\|\*\*创始人\*\*.*?\|.*?\|.*?\|.*?\|'
    new_founder_sw = f'| **创始人** | 🗣 端口规范v2 签字会议（4条决定已定） | 🔄 进行中 | 本周 |'
    content = re.sub(old_founder_sw, new_founder_sw, content)
    
    # 更新 G3 状态行：添加备注
    # 找到 G3 那行的「深度修复完成，待创始人验收」替换
    content = content.replace(
        '深度修复完成，待创始人验收',
        '深度修复完成（暂缓，优先推进端口规范v2）'
    )
    
    with open(board_sw, 'w', encoding='utf-8') as f:
        f.write(content)
    print('  ✅ 软件推进看板.md 已更新')
except Exception as e:
    print(f'  ⚠️ 软件推进看板.md 更新失败: {e}')
"
  
  # 如果不是最后一次，等 5 分钟
  REMAINING=$((END_TIME - $(date +%s)))
  if [ $REMAINING -gt 0 ]; then
    WAIT=$((REMAINING < 300 ? REMAINING : 300))
    echo "  ⏳ 等待 ${WAIT} 秒后下次推送..."
    sleep "$WAIT"
  fi
done

echo ""
echo "✅ 端口规范v2进度推送 完成！共推送 $COUNTER 次"
