# 行为学训练盒（Behavior Box）

仓鼠/小鼠操作性条件反射训练的自动化上位机软件。不需要编程知识，浏览器打开即用。

## 当前版本

**v1.1.0** — G3 流程编辑器深度修复完成，待创始人验收。G1/G1.5/G2 已关门。

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
