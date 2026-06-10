# 行为学训练盒（Behavior Box）

仓鼠/小鼠操作性条件反射训练的自动化上位机软件。不需要编程知识，浏览器打开即用。

## 当前版本

**v1.1.3** — 五条典型链路门禁通过；第 5 条“每日定额投喂 / 可持久斯金纳箱”最小可验版已完成。CSV / 导出 / 图表仍归 G4。

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

- 应进入版本库：`software/` 下源码与测试、`software/e2e/`、`scripts/` 里的运维脚本、根目录 `package.json` / `playwright.config.js`、`AGENTS.md`
- 本地运行产物：`software/data_store/`、`.playwright-mcp/`、`node_modules/`、`playwright-report/`、`test-results/`
- 若想快速看懂当前工作区为什么变脏，可运行 `./scripts/audit_worktree.sh`

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
