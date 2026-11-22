# 多智能体软件项目管理模拟平台

面向《软件项目管理》实验的 LangGraph + FastAPI + React 应用。内置 Library Management System 示例，支持 Mock/真实模型决策、Human/模拟发起人审批，以及五大过程组的完整教学模拟。

**所有项目开发、缺陷与测试成果均为模拟结果；pytest 和浏览器测试验证的是平台软件本身。**

## 在当前目录直接启动

```powershell
cd D:\大三上\软件项目管理\code
.\.venv\Scripts\python.exe -m app.serve
```

打开 [Dashboard](http://127.0.0.1:8000)，点击“运行 Mock 示例”。现有目录已完成前端构建。API 文档位于 [/docs](http://127.0.0.1:8000/docs)。APP_PORT 进程环境变量可修改默认 8000 端口。

原始教材与课程文件保留在上一级目录。架构见 [architecture.md](docs/architecture.md)，开发记录见 [implementation-plan.md](docs/implementation-plan.md)，逐项验收和验证边界见 [validation.md](docs/validation.md)。

## 从源码安装与构建（Windows）

需要 Python 3.12+、Node.js 24、pnpm 11；前端 packageManager 固定为 pnpm 11.25.0。Python 和前端依赖分别记录在 requirements-lock.txt、frontend/pnpm-lock.yaml。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
cd frontend
pnpm install --frozen-lockfile
pnpm run build
cd ..
.\.venv\Scripts\python.exe -m app.serve
```

Mock 模式不需要 .env 或 API Key。真实模式在项目根目录的本地 .env 设置 LLM_BASE_URL、LLM_MODEL、LLM_API_KEY；模板见 .env.example。已有 .env 请保留。应用入口加载该文件，进程环境变量优先；密钥不会进入前端产物。LLM_TIMEOUT_SECONDS 默认 30，允许大于 0 且不超过 120 秒。一次回复上限 2048 tokens，校验/调用失败最多尝试三次，不能静默切换 Mock。

服务器只监听本机，保持一个 worker。业务 SQLite 和相邻 *.checkpoints.db 请一起备份；启动时执行 Alembic 迁移，未知旧结构拒绝自动接管。数据库默认位于启动目录的 simulator.db，可用 DATABASE_URL 指定。降级应恢复备份。

## Web 实验流程

1. “运行 Mock 示例”创建图书管理实验，后台自动算完后从第 0 日播放已保存的逐日记录；“新建实验”默认开启“逐日演示”，每个模拟工作日后真正暂停，可点下一日或播放继续。
2. Mock 可选图书管理和实验室预约两套预设任务及相应变更；其他需求使用单任务通用演练。自定义需求若需要语义化拆解，需配置真实模型并验证输出。
3. 实验总览查看五过程组、六角色、每日活动、验收进度、PV/EV/AC、SPI/CPI、关键路径与偏差解读。上一日、下一日、播放、暂停和滑条可回看历史。
4. 范围与计划查看项目章程、干系人、约束、SRS 验收标准、WBS、依赖和计划甘特图。模拟日滑条可查看历史指标及其对应批准基准。
5. 协作与轨迹按角色查看结构化输出、校验结果、耗时、provider 和输入摘要；工作流事件支持展开全部持久记录。
6. 变更与审批查看 PM 提案、成本/工期影响、剩余计划及 PV 锚点、新旧基准和审批结果。
7. 结项报告可下载 JSON。点击“生成实验报告”填写组员、分工和反思，上传 Microsoft Project 的 WBS 与甘特图截图，再用浏览器打印为 PDF。文字字段保存在本机浏览器；图片在关闭报告页后需重新选择。

Human 模式在章程、计划、变更、最终验收四个版本绑定审批点暂停。审阅产物后选择批准/拒绝，UI 自动请求顶层交付图继续。刷新页面或重启服务保留进度；项目选择器可重新打开历史实验。拒绝章程、计划或最终验收会保留未完成状态；修订目标时应显式开始新实验。拒绝变更则沿原基准继续。

内置 Mock v7 图书管理场景的复现结果：初始四个模块、一次模拟缺陷与返工、一次逾期提醒需求变更、两版正式基准；9 个模拟工作日完成，最终 BAC=EV=40,000 分，AC=45,000 分。PM 在合法任务中分配工作，Developer/Tester 输出不能改写引擎事实，进度成本分析师解释 Python 计算的指标。

模拟规则：一个 tick 为一个工作日，五日工作周、每日 8 小时、无节假日；资源按容量分配；EV 采用叶子任务 0/100 模拟验收计量。返工增加 AC 而不重复挣值。CPM 不考虑资源等待。变更后的未来 PV 从历史累计值锚点起，在剩余依赖预测区间内均匀分配，尾日吸收整数分余数；依据必须先审批并写入不可变基准。模型和模拟结果不能代替实际代码执行。

## Microsoft Project 任务计划导出

范围与计划页可下载所选基准的 MSPDI XML，或使用：

```text
GET /api/v1/runs/{run_id}/export?baseline_version=2&start_date=2026-11-16
```

包括稳定任务 UID、WBS、工期、依赖及 FS lag、五日工作日历、CPM 起止日期和批准预算。默认起始日取项目创建时的上海日期并顺延到工作日。预算按固定成本导出，不生成资源分配费用，避免重复计算。文件是 **CPM 任务网络计划**；不导出平台的聚合 PV 桥接或模拟实际工时/进度，PercentComplete 为 0，标题和备注明确标为模拟计划。

已验证 XML 解析、字段映射、日期/成本/依赖和浏览器下载；本机未检测到 MSProject.Application 注册项，尚未进行 Microsoft Project 原生导入验证。格式依据和详细边界见 [validation.md](docs/validation.md)。

## 测试与开发

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe scripts/smoke_local.py
cd frontend
pnpm run build
pnpm run test:e2e
```

浏览器测试在 Windows 使用本机 Edge 的全新无头会话。测试和命令行冒烟均使用临时 SQLite，不修改用户项目，也不调用真实模型。脚本验证结束会停止自有 QA 服务。app.serve 在 Windows 使用 Selector 事件循环，避免刷新 SSE 时的 Proactor 连接重置日志。

开发时可另开终端，在 frontend 运行 pnpm dev；Vite 将 /api 代理到 127.0.0.1:8000。生产构建由 FastAPI 同源托管，不需要独立前端服务器。

## 主要 API

| 路径 | 用途 |
| --- | --- |
| POST /api/v1/projects | 保存需求与实验配置 |
| POST /api/v1/projects/{id}/delivery | 幂等启动顶层交付图，需 Idempotency-Key |
| GET /api/v1/runs/{id}/delivery | 状态与待审批对象 |
| POST /api/v1/runs/{id}/delivery/resume | 人工决策后或故障修复后恢复 |
| GET /api/v1/runs/{id}/artifacts、traces、events | 产物、执行轨迹、支持 Last-Event-ID 的 SSE |
| GET /api/v1/runs/{id}/simulation | 逐日指标、当前任务快照和批准范围 |
| GET /api/v1/runs/{id}/baselines、changes | 不可变基准与正式变更历史 |
| GET /api/v1/runs/{id}/simulation/report | 候选/最终管理报告及验收状态 |
| GET /api/v1/runs/{id}/export | 批准版本的 MSPDI XML |

低层角色、计划审批和模拟 API 保留用于逐步教学；不要与同一项目的顶层交付操作混用。完整真实模型交付流程尚未外部验证；已验证模型发现、Sponsor 输出和审批调用，见 [真实模型连接记录](docs/real-provider-verification.md)。
