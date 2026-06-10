# 行为学训练盒 — 上位机软件

> 2026-06-10 更新，版本 v1.1.3（第5链路最小持久状态能力后）

## 产品定位

仓鼠/小鼠操作性条件反射训练的 Web 上位机。用户是生物学实验人员，不需要编程知识。
浏览器打开 `http://localhost:8000` 即用。

## 技术栈

| 层 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn (Python 3) |
| 实时通信 | WebSocket |
| 数据库 | SQLite (WAL模式) |
| 前端 | 纯 HTML/CSS/JS，无框架 |
| GUI | PyQt6（`main.py` 桌面模式） |
| 测试 | pytest + httpx |
| 硬件协议 | BLE / Serial (ESP32) |

## 软件架构

```
software/
├── server.py              # [入口] FastAPI Web 服务器 (端口8000)
├── main.py                # [入口] PyQt6 桌面应用
├── cli_app.py             # [入口] CLI 命令行工具
│
├── protocol/              # 信号输入层 — 统一抽象所有输入源
│   ├── signal_source.py   #   抽象基类 + Mock/Timer/Camera 实现
│   ├── signal_bus.py      #   多源汇集 + 归一化时间戳 + 投喂引擎
│   ├── messages.py        #   事件类型枚举 (EventKind)
│   ├── device_manager.py  #   ESP32 设备管理
│   ├── device_registry.py #   注册中心三合一（信号源/执行器/记录事件）
│   ├── transport.py       #   抽象传输层
│   ├── ws_transport.py    #   WebSocket 传输
│   └── ble_transport.py   #   BLE 传输
│
├── session/               # 实验会话层 — 流程编排 + 引擎调度
│   ├── flow_model.py      #   流程图数据模型：13种节点 + 边 + 图
│   ├── engine.py          #   运行时引擎：消费信号 → 执行节点
│   ├── validator.py       #   流程校验器：语法+语义双层
│   └── session.py         #   会话生命周期管理
│
├── data/                  # 数据层 — 持久化 + 查询 + 导出
│   ├── database.py        #   SQLite 连接管理 (WAL, busy_timeout)
│   ├── event_store.py     #   事件增删改查
│   ├── quota_state.py     #   第5链路最小持久状态（投喂额度/冷却）
│   ├── experiment_manager.py  # 实验文件夹管理 (自包含)
│   ├── export.py          #   CSV 导出
│   └── processor.py       #   数据处理
│
├── web/                   # 前端 (纯 HTML/CSS/JS，无框架)
│   ├── index.html         #   SPA 页面
│   ├── project-dashboard.html  # 项目管理仪表盘
│   ├── css/style.css      #   样式
│   └── js/
│       ├── app.js         #   主逻辑 + 实验管理
│       ├── camera.js      #   摄像头配置 (~2000行)
│       ├── flow-model.js  #   流程数据模型 + Schema 定义
│       ├── flow-canvas.js #   流程画布渲染 (节点/连线/拖拽)
│       └── flow-editor.js #   流程编辑器交互 (面板/配置/校验)
│
├── ui/                    # PyQt6 桌面 UI
│   ├── camera.py
│   ├── charts.py
│   └── flow_editor.py
│
├── hardware/              # 硬件烧录工具
│   ├── burner.py          #   ESP32 固件烧录
│   └── env_installer.py   #   环境安装
│
├── utils/                 # 工具函数
│   └── logger.py
│
├── tests/                 # pytest 测试 (134 tests, 127 pass)
└── data_store/            # [运行时数据] 不提交 git
    ├── behavior_box.db
    ├── camera_config.json
    └── experiments/       # 每个实验一个文件夹
```

## 核心数据流

```
信号源 (Camera/Device/Timer/Mock)
    → SignalBus (汇集+归一化)
        → Engine (流程引擎, 消费信号 → 按 FlowGraph 调度)
            → Session (会话状态追踪)
                → EventStore → SQLite
                → WebSocket → 前端实时更新
                → CSV 导出
```

## 流程模型 (13种节点)

| 类别 | 节点 | 输入 | 输出 | 说明 |
|------|------|:---:|:---:|------|
| 固定 | START | 0 | 1 | 流程入口 |
| 固定 | END | ≥1 | 0 | 流程出口 |
| 触发 | TRIGGER | ≥1 | 1 | 等待信号触发（从注册中心选择信号源） |
| 延时 | DELAY | ≥1 | 1 | 等待 duration_s 秒后通过 |
| 条件 | CONDITION | 1 | 2(true/false) | 根据上游数据做条件判断，支持 source/neq |
| 动作 | EXECUTE | ≥1 | 1 | 执行动作指令，从注册中心选择执行器 |
| 逻辑 | AND | ≥2 | 1 | 全部信号到齐才输出 |
| 逻辑 | NOT | 1 | 1 | 等待信号消失后输出 |
| 控制 | LOOP | 1 | 2(body/exit) | 循环，max_iter/timeout 或退出 |
| 控制 | FORK | 1 | 2(continue/stop) | 无条件分叉 |
| 探针 | SNIFFER | 0 | 0 | 独立旁路监听，不参与流程拓扑 |
| 记录 | RECORD | ≥1 | 1 | 记录数据点，可选计数器操作 |
| 记录 | RECORD_END | ≥1 | 0 | 记录后终止分支，可选计数器操作 |

## 关键约定

### 端口规则
- 每个输入端口最多 1 条入边（≤1）
- 每个输出端口最多 1 条出边（≤1）
- 同端口对不重复连线
- FORK/LOOP/CONDITION 双出口标签用 pill 形状
- START 不能作为连线目标，END 不能作为连线来源

### 参数命名
- 时间参数统一用秒（`duration_s`、`timeout_s`），前端 Schema 和后端引擎必须一致
- 前后端字段名同时修改，不能分批次

### 循环检测
- "有 LOOP 的环" → warning，放行
- "无 LOOP 的环" → error，拒绝

### 注册中心
- `device_registry.py` 统一管理三类资源：信号源/执行器/记录事件
- TRIGGER/EXECUTE 节点的 signal_id/actuator_id 均从注册中心动态加载
- 摄像头 zone 在配置保存时自动注册为信号源
- `GET /api/sources` 和 `GET /api/registry/*` 对外暴露

### 文件存储
- 每个实验一个文件夹：`data_store/experiments/{名称}/`
- 包含：`experiment.json` + `flow.json` + `camera.json` + `events.db` + `exports/`
- 创建实验时即刻初始化占位 flow.json

### 数据库
- `busy_timeout=5000` + `journal_mode=WAL` 防止并发锁
- 写操作必须 commit()
- `raw_payload` 读后需检查类型（可能是 str 或 dict）

### 第5链路持久状态
- 本轮只按投喂次数/颗数计量，不按克数；硬件负责单次出粮请求对应的实际食物量
- 不新增通用 FLAG 节点
- `RECORD` 是持久状态写入口，`CONDITION` 读取持久状态
- 最小落盘字段：`feeds_today`、`daily_quota_count`、`quota_locked`、`cooldown_until`、`day_index`
- 当前实现是“配额周期”最小能力；自然日切换、CSV、导出、图表归后续 G4/G5，不纳入 Sprint v1.1.3 门禁

### XSS 防护
- 所有用户输入的字符串插入 innerHTML 前必须 `escapeHtml()`
- `escapeHtml()` 在 `app.js` 定义，后续 JS 文件全局可用

## 测试

| 套件 | 数量 | 状态 |
|------|:---:|:----:|
| test_api.py | 17 | ✅ |
| test_event_store.py | 10 | ✅ |
| test_experiment_manager.py | 9 | ✅ |
| test_export.py | 8 | ✅ |
| test_flow_schema.py | 51 | ✅ |
| test_quota_state.py | 4 | ✅ |
| test_zone_state_machine.py | 10 | ✅ |
| test_bug_regression.py | 24 | ✅ |
| test_validator_loop.py | 7 | ✅ |
| test_device_registry.py | 20 | ✅ |
| 5 ad-hoc bug tests | 5 | ✅ live server |
| Playwright 第5链路专测 | 2 | ✅ |
| Playwright 五链路门禁 | 1 | ✅ |
| **本轮相关** | **74 pytest + 3 Playwright + 5 live-server** | **✅ 全过** |

运行：`cd software && python3 -m pytest tests/ -v`

> 注：全量 pytest 当前仍受旧 `TestClient/httpx` 兼容问题影响，不能把该环境问题等同于第5链路门禁失败。

## 启动

```bash
cd software
python3 server.py --port 8000
# 浏览器: http://localhost:8000
```

或 `./scripts/manage.sh start/stop/restart/status`

## 项目文档

| 文档 | 路径 |
|------|------|
| **活动日志** | `项目/00_活动日志.md` |
| PM 交接文档 | `项目/07_会议与沟通/软件交接文档.md` |
| 软件推进看板 | `项目/01_阶段规划/软件推进看板.md` |
| Bug 跟踪 | `项目/04_验收与测试/Bug跟踪.md` |
| 推进看板 | `项目/01_阶段规划/推进看板.md` |
| PRD | `项目/02_范围与需求/PRD_产品需求文档_V1.md` |
| 验收清单 | `项目/04_验收与测试/C_软件验收清单.md` |
| 风险登记册 | `项目/06_风险与决策/风险登记册.md` |
| 测试报告 | `项目/07_会议与沟通/测试报告.md` |
| 本次任务单 | `项目/07_会议与沟通/本次任务单.md` |
| 决策记录 | `项目/06_风险与决策/决策记录.md` |

## 开发铁律

1. **AGENTS.md 是最新权威信息源**，代码即真相
2. **新增节点必须三端同步**：flow_model.py → validator.py → flow-editor.js Schema
3. **前后端参数名和单位必须完全一致**
4. **先行测试再改代码**：复杂状态机用 Python 模拟器验证
5. **UI 门控 = 数据安全**：所有编辑功能必须在有明确归属实体时启用
6. **模仿 X 设计 = 列出 X 的所有行为清单**，逐条对齐
7. **不替外包方做技术决策**：芯片、协议、技术栈由外包方自定
8. **文档即契约**：所有共识写入文档
