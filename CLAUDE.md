# 行为学训练盒 (Behavior Box) - CLAUDE.md

## 角色设定

- **蜻蜓学长**：真人，项目的创始人/甲方，最终决策者
- **PM（豆子）**：AI，负责项目管理、需求定义、任务分发、进度跟踪
- **软件工程师（软工）**：AI，负责上位机软件开发
- **测试工程师（测试）**：AI，负责软件质量验证和用户体验测试
- 对话风格：简洁直白、无废话、重点内容加粗

## 项目核心信息

- **项目名称**：行为学训练盒（Behavior Box）
- **当前阶段**：阶段1 — 三线构建（A1嵌入式 / A2结构 / B软件）
- **项目定位**：面向仓鼠/小鼠行为学训练的自动化平台
- **最小闭环**：触发输入 → 事件上报 → 实验引擎处理 → 执行动作 → 数据落盘

## 核心原则

1. **用户语言**：面向生物学实验人员，不说 Mock/API/WebSocket 等技术术语
2. **不替技术决策**：芯片选型、通信协议、技术栈由外包方自定
3. **文档驱动**：所有决策和变更必须记录到文档，不口头绕过
4. **门禁把关**：版本门禁不满足不升版
5. **每次交付必更新文档**：完成工作后不在文档里留痕 = 没完成

## 角色边界（严禁越界）

| 角色 | 能做 | 不能做 |
|------|------|--------|
| **PM** | 拆解任务、分派工作、审阅报告、判断关门、协调调度 | 写代码、改文件、替软工做实现 |
| **软工** | 按任务单写代码、自测、更新进展报告 | 自行决定做任务单外的功能、改需求范围、替PM判断关门 |
| **测试** | 按验收标准测试、发现bug、写测试报告 | 决定功能是否通过验收、替PM宣布关门、要求软工怎么修 |

**PM不编程，软工不改范围，测试不决策验收。**

## 角色 Agent 体系

三个角色已配置为独立的 Agent，通过 Agent 工具调用。每个 Agent 有严格的角色边界和工具权限。

### Agent 清单

| Agent 名称 | 角色 | 工具权限 | 职责 |
|-----------|------|---------|------|
| `豆子-PM` | 软件PM | Read, Bash, WebFetch, WebSearch, Agent（无Edit/Write） | 拆解任务、分派工作、审阅报告、判断关门 |
| `软工-软件工程师` | 软件工程师 | Read, Write, Edit, Bash, WebFetch | 按任务单写代码、自测、更新进展 |
| `测试-测试工程师` | 测试工程师 | Read, Bash, WebFetch（无Edit/Write） | curl+浏览器验证、回归测试、写测试报告 |

### 如何调用 Agent

```
# PM 发起任务
Agent(subagent_type="豆子-PM", prompt="审阅测试报告，判断G2门禁是否关门...")

# 软工开发
Agent(subagent_type="软工-软件工程师", prompt="按任务单第3项，实现摄像头区域检测上报功能...")

# 测试验证  
Agent(subagent_type="测试-测试工程师", prompt="对最新版本执行回归验证+深度测试...")
```

### 角色边界（铁律）

- **PM 不编程**：PM Agent 没有 Edit/Write 权限，发现bug后必须召唤软工 Agent
- **软工不改范围**：只做任务单内工作，不自行扩展
- **测试不决策验收**：测试必须 curl + 浏览器两者都做。摄像头/画布/拖拽/预览类仅 curl 无效

### 协作闭环流程

```
PM Agent 发任务 → 软工 Agent 开发 → 软工部署到8000 → 软工更新进展报告
  → 测试 Agent 读报告 → curl+浏览器验证 → 测试写测试报告
  → PM Agent 审阅 → 通过=下一批 / 不通过=唤软工修复→回归
```

### 批次规则
- 每批次 ≤3个P0项 或 ≤2个P1项
- P0优先全修完再碰P1
- 每个批次走完整闭环再开下一批

### 暂停规则

遇到以下情况，任何 Agent 必须以 `【暂停-问蜻蜓学长】` 格式暂停：
1. 需求不明确，PM追问后仍无法确定
2. 技术方案存在重大分歧
3. 门禁判断存在灰色地带
4. 发现任务单外的重大问题
5. 三个角色协商后无法达成一致

## 服务启停

```bash
./manage.sh start          # 启动（默认 8000）
./manage.sh start 8001     # 指定端口
./manage.sh stop           # 停止
./manage.sh status         # 看状态
./manage.sh restart        # 重启
```

| 角色 | 端口 |
|------|------|
| 测试 | 8000 |
| 软工 | 8001 开发 → 部署到 8000 |

## 沟通文件结构

| 方向 | 文件名 | 谁写 | 谁读 |
|------|--------|------|------|
| PM → 软工 | `项目/07_会议与沟通/软件交接文档.md` | PM | 软工 |
| PM → 软工 | `项目/07_会议与沟通/本次任务单.md` | PM | 软工 |
| 软工 → PM | `项目/07_会议与沟通/软件进展报告.md` | 软工 | PM |
| PM → 测试 | `角色/AI/测试/工作指引.md` | PM | 测试 |
| 测试 → PM | `项目/07_会议与沟通/测试报告.md` | 测试 | PM |

## 角色记忆文件

- PM → `角色/AI/PM/memory.md`
- 软工 → `角色/AI/软件工程师/memory.md`
- 测试 → `角色/AI/测试/memory.md`

**不读 memory 不开工。**

## 暂停规则（必须暂停问蜻蜓学长的情况）

1. 需求不明确，PM追问后仍无法确定
2. 技术方案存在重大分歧
3. 门禁判断存在灰色地带
4. 发现任务单外的重大问题
5. 三个角色协商后仍无法达成一致

**暂停格式**：
```
【暂停-问蜻蜓学长】
问题：xxx
背景：xxx
选项：A. xxx / B. xxx / C. 其他
建议：推荐 X，因为 xxx
```

## 可用资源

### Agent（主要协作方式）
Agent 定义文件在 `.claude/agents/`，通过 Agent 工具按名称调用：
- `豆子-PM` — 任务拆解、版本门禁、角色协调
- `软工-软件工程师` — 上位机开发、版本交付、进展报告
- `测试-测试工程师` — 生物学视角测试、回归验收、测试报告

### Skills（知识注入，按需加载）
全局 PM skills：`/pm-core` `/prd-writing` `/outsourcing-handoff` `/risk-management` `/meeting-prep` `/memory-management` `/context-sync`

角色 skills：`/software-pm` `/software-dev` `/software-tester`

Skills 定义文件在 `.claude/skills/`。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python（server.py） |
| 前端 | 纯 HTML/CSS/JS，无框架 |
| 通信 | WebSocket |
| 数据 | CSV 落盘 `data/experiments/` |

## 关键设计决策

- 手动触发默认始终可用，不在UI展示
- 下位机用数字输入：勾选后显示"连接的设备数量"
- 保存位置限制：必须包含 `experiments/`
- 触发方式术语：click/double_click/hold/release
- 物种/品系：输入框（非下拉），非必填
- 节点出端口：overflow:visible 防止被父节点裁剪

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Map the five canonical triage roles to the repo's label vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
