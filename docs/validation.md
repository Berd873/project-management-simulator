# 最终验收记录

M0—M5 的本地 Web 模拟平台已交付。内置 Library Management System 在无 API Key 的 Mock 模式下，经网页完成需求、章程、规划、开发/测试反馈、监控、一次批准变更及最终 Sponsor 验收。所有 LMS 交付和测试结论都是模拟；以下 pytest、浏览器测试和冒烟实际验证平台软件。

## 验证结果

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| `python -m pytest -q --tb=short` | 88 passed，61.80s | 数据模型、迁移、角色校验、图路由、持久恢复、CPM/EVM、模拟、正式审批/变更、报告与导出 |
| `pnpm run build` | 通过 | TypeScript 检查与 Vite 生产构建 |
| `pnpm run test:e2e` | 3 passed | Windows 无头 Edge；Mock 全流程、Human 四审批点、拒绝章程与刷新恢复 |
| `python scripts/smoke_local.py` | 通过 | 实际启动 `app.serve`，HTTP 访问生产 UI、Mock 交付、最终报告及 MSPDI 下载 |
| 配置与产物检查 | 通过 | `.env` 被忽略；配置中的密钥未出现在文档与前端 dist |

最后一次浏览器运行的 `.last-run.json` 为 passed。截图测试另有滚动归零调整，不改变应用代码。测试数据库均隔离；脚本退出时停止其测试服务。

## 逐项功能证据

| 目标要求 | 实现与验收证据 |
| --- | --- |
| 六角色及职责边界 | `agents/contracts.py`、`agents/providers.py`；角色、引用、Schema、容量/授权及业务验证；非法决策最多三次，不能静默切换 Mock |
| LangGraph 唯一控制流程 | `workflows/delivery.py` 顶层图协调角色图、计划审批图和模拟图；PM 仅产生提案、分配及管理建议 |
| 五过程组 | 章程启动；SRS/WBS/估算与批准计划；逐日执行；EVM/风险/变更监控；最终批准和归档。UI 展示相应过程组 |
| Charter、SRS、WBS、计划 | 不可覆盖的 Artifact，包含约束、干系人、依赖及验收标准；`plan_builder.py` 由估算确定性计算成本 |
| Developer–Tester 循环 | `execution_agents.py` 及模拟引擎；模拟首测失败→修复→回归，Tester 不能改写引擎事实，伪造输出不能提交当天成本/进度 |
| CPM | `services/planning.py`，FS/lag、前后向计算、总浮时、关键任务/边、五日工作周；测试非法环/引用及日期映射 |
| EVM | 同服务计算 PV/EV/AC、SV/CV、SPI/CPI、EAC；整数分和 Decimal；零分母返回原因。EV 使用验收后 0/100 规则 |
| 可复现模拟 | `services/simulation.py` 纯 step，保存 seed、场景/引擎版本和 RNG；资源容量、返工及日数上限；相同授权决策重放一致 |
| 正式变更及基准历史 | `baselines.py`、`rebaseline.py`；版本绑定审批、确定性影响分析、新旧基准与不可变触发器；保存批准的剩余计划/PV 锚点及源快照 hash |
| 暂停/恢复与审计 | SQLite checkpointer、业务 NodeReceipt、AgentExecution 与 Event；进程边界恢复、事务提交后 checkpoint 前崩溃重放、重复/过期审批测试 |
| React Dashboard | 五个页面展示六角色轨迹、完整 SSE 事件、WBS、甘特、关键任务、指标曲线、人工审批、变更及报告；刷新可重开同一 run，390px 移动视口无横向溢出 |
| 管理报告 | `services/reports.py`；范围/测试次数、最终绩效、风险建议、管理经验、基准/变更、复现信息及最终 Sponsor 决定；可下载 JSON |
| Microsoft Project 计划导出 | `services/project_export.py`；已批准版本的 MSPDI XML，测试稳定 UID、日历、FS lag、日期、成本、版本选择及实际浏览器下载 |
| 真实模型配置 | 本地 `.env` 支持 OpenAI 兼容 API；模型发现及 Sponsor 两类决策的外部调用记录见 real-provider-verification.md |

测试文件位于 `backend/tests/`；浏览器用例位于 `frontend/tests/dashboard.spec.ts`。UI 证据：[桌面](screenshots/dashboard-desktop.png)、[移动端](screenshots/dashboard-mobile.png)。

## Mock LMS 最终结果

当前 Mock provider 为 `mock:v6`，prompt 为 `mock-decisions-v6`。内置默认案例完成 9 个模拟工作日；最终 BAC=EV=40,000 分（¥400），AC=45,000 分（¥450），PV=40,000 分，SPI=1，CPI=8/9。范围由四模块变为五项任务，包含一次模拟缺陷修复、一次批准变更、两版正式基准以及最终验收。这里的天数和成本是教学参数。

Human 模式包含章程、初始计划、变更、最终验收四个明确审批点；各点重建服务后均能恢复。拒绝章程不会开始模拟；拒绝变更继续旧范围；拒绝最终验收保留拒绝理由，不能将项目标为完成。

## 导出依据与验证边界

MSPDI 字段依据 Microsoft 的 [Project XML 结构](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/project-elements-and-xml-structure?view=project-client-2016)、[Task 元素](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/task-elements-and-xml-structure?view=project-client-2016)及 [Calendar 元素](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/calendar-elements-and-xml-structure?view=project-client-2016)文档映射。

输出包含五日/八小时日历、稳定 UID、WBS、CPM 起止、Duration、FS 依赖与 lag、CNY 固定预算成本。资源仅在 Notes 说明，未创建资源分配费用；PercentComplete 为 0，不导出模拟 ActualWork/ActualCost。导出是批准范围的依赖网络计划，未将资源排程或平台聚合 PV 桥接冒充 Project 原生基准曲线。

本机未检测到 `MSProject.Application` 注册项。已完成 XML 解析、字段/单位断言和下载验证，**未进行 Microsoft Project 原生导入，也未执行完整官方 XSD 校验**。具备 Project 环境后仍需打开导出 XML，核对日历、起止、依赖、WBS 与成本。

## 运行假设与剩余扩展

- 本机单进程、一个 worker；无多用户认证、分布式锁或共享部署保证。业务 SQLite 与 checkpoints 文件需一起备份。
- CPM 是依赖网络计算，不做资源平衡；模拟引擎另外遵守资源容量。工作周不含节假日。
- 变更在完成某日 tick 后审批；该日历史指标仍用旧基准，后续日使用批准的新基准。新 PV 从历史累计值锚定，将剩余 BAC 按剩余依赖预测区间均摊；假设、源快照 hash 与剩余预测一并批准保存，历史不回写。
- Mock 可按 seed/版本重放；真实模型须使用已保存的验证决策重放，单凭 seed 不保证模型输出相同。
- 真实模型只验证模型发现、Sponsor 输出与审批输出；完整六角色真实模型交付尚未外部验证。
- 平台不执行真实 LMS 代码，不将模拟测试视为实际测试；真实代码开发/执行仍为后续可选扩展。

上述边界不阻断当前 Goal 的 Mock Web 模拟验收。启动、安装及 API 操作见根目录 README.md。
