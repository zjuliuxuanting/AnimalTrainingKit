# 行为学训练盒（Behavior Box）

仓鼠/小鼠操作性条件反射训练的自动化上位机软件。不需要编程知识，浏览器打开即用。

## 当前版本

**v1.1.5-dev** — G3 关门前收尾：摄像头/手动触发驱动流程、用户主路径信号口收缩、实时日志面向实验人员。CSV / 导出 / 图表仍归 G4。

## 技术栈

| 层 | 技术 |
|------|------|
| 后端 | FastAPI + Uvicorn (Python 3) |
| 实时通信 | WebSocket |
| 数据库 | SQLite (WAL 模式) |
| 前端 | 纯 HTML/CSS/JS，无框架 |
| 测试 | pytest + httpx (134 tests, 127 pass) |

## 快速开始

```bash
cd software
pip install -r requirements.txt
python3 server.py --port 8000
# 浏览器打开 http://localhost:8000
```

或 `./scripts/manage.sh start`

## 版本产物归属

Git 版本库应只保存源码、测试、必要脚本和少量对外同步文档。

- 应进入版本库：`software/` 下源码与测试、`software/e2e/`、`scripts/` 里的运维脚本、根目录 `package.json` / `playwright.config.js`
- 本地运行产物：`software/data_store/`、`.playwright-mcp/`、`node_modules/`、`playwright-report/`、`test-results/`
- 本地协作配置：`.agents/`、`.claude/`、`.codex/`、`.trae/`、`.workbuddy/`、`.vscode/`、`.mcp.json`。这些目录用于 AI/IDE/协作环境，默认不挪动、不提交。
- 若想快速看懂当前工作区为什么变脏，可运行 `./scripts/audit_worktree.sh`

## 根目录地图

| 路径 | 归属 | 处理规则 |
|------|------|----------|
| `software/` | 上位机软件源码、测试、前端资源 | 主要开发目录 |
| `scripts/` | 服务管理、工作区审计等脚本 | 可提交 |
| `项目/` | PM、测试、验收、交接文档 | 当前协作真相面，按任务更新 |
| `角色/` | AI 角色记忆与交接材料 | 按角色流程更新 |
| `.agents/` | 项目技能与 agent 配置 | 本地协作能力，保持原位 |
| `.claude/` `.codex/` `.trae/` `.workbuddy/` `.vscode/` | 本地 AI/IDE 配置 | 不作为软件交付物整理 |
| `.playwright-mcp/` | 浏览器测试运行缓存 | 可清理，不作为源码 |
| `_存档/` | 历史资料归档 | 不默认删除 |

## 项目结构

```
behavior_box/
├── software/           # 上位机软件
│   ├── server.py       # FastAPI 入口
│   ├── protocol/       # 信号输入层
│   ├── session/        # 实验引擎 + 流程模型
│   ├── data/           # 数据持久层
│   ├── web/            # 前端 (HTML/CSS/JS)
│   ├── tests/          # pytest 测试
│   └── data_store/     # 运行时数据（不提交 git）
├── 项目/               # 项目管理文档
├── 角色/               # AI 角色工作空间
└── scripts/            # 运维脚本
```

## 文档索引

| 文档 | 路径 |
|------|------|
| 项目总览 | `项目/00_索引与总览.md` |
| 战略规划 | `项目/00_战略规划.md` |
| PRD | `项目/02_范围与需求/PRD_产品需求文档_V1.md` |
| 软件使用说明 | `项目/07_会议与沟通/软件使用说明.md` |
| 验收清单 | `项目/04_验收与测试/V1_验收清单.md` |
| 当前任务单 | `项目/07_会议与沟通/本次任务单.md` |
| 架构详情 | `CLAUDE.md` (本文档根目录，给 AI 开发者看) |

## License

MIT
