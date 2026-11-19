# 按依赖顺序的开发清单

M0—M5 已完成；最终验证为 88 项后端测试、3 项浏览器 E2E、生产构建及独立启动冒烟通过。以下阶段记录按开发时间保留，当时的“尚未完成”说明不代表当前状态。验收范围与限制见 validation.md。

## M0：设计（先于所有实现）

- [x] 检查现有仓库和工程环境，保留原始课程材料。
- [x] 架构、角色契约、StateGraph、数据库、计算引擎和 API 设计。
- [x] 确定 M1 边界及后续依赖，不提前实现工作流和 UI。

## M1：基础工程和核心数据模型（依赖 M0）

- [x] Python 3.12 工程配置、可安装 backend 包、开发依赖。
- [x] 模式/角色/过程组枚举；Pydantic 创建及读取 Schema。
- [x] SQLite Session 生命周期、外键和等待配置。
- [x] Project、草案 Task、版本化 Artifact SQLAlchemy 模型及基础约束。
- [x] FastAPI 工厂、数据库初始化、health、项目创建/列表/详情、OpenAPI。
- [x] 真实运行基础 pytest：输入校验、API、文件数据库重启持久化、约束和回滚。
- [x] README、环境示例与安装版本快照。

验收：无 API Key 可以启动 API、创建/读取项目，非法输入被拒绝；重建 app 后数据仍在。本阶段不启动任何模拟。测试执行结果见本文件末尾。

## M2：六角色与 LangGraph 骨架（依赖 M1）

1. [x] 引入 Alembic，验证 M1 数据升级；添加 run、trace、approval、event、receipt 表。
2. [x] 定义领域产物 Schema、AgentContext、DecisionEnvelope 及业务校验器。
3. [x] 实现 Mock provider 和六角色适配器，记录版本化执行轨迹。
4. [x] 实现 real provider 配置、结构化校验、有限重试、脱敏及显式失败。
5. [x] StateGraph 和固定条件路由，执行及计算显式停在 awaiting_m3，不声称完整演示。
6. [x] SQLite checkpointer、human interrupt/resume、单 run 锁及幂等事务。
7. [x] run/审批/SSE API；测试暂停后进程重建、重复审批、非法 Agent 输出与提交后崩溃重放。

验收：角色通过 graph 调用，人工审批可恢复，重试不重复业务副作用；尚未实现计算与项目闭环。

## M3：计算与模拟（依赖 M2）

1. [x] 资源/依赖嵌入计划 JSON、进度/RNG/指标嵌入 SimulationTick；Alembic 0003；工作日历及整数分规则（见设计调整）。
2. [x] CPM DAG 前后向计算、稳定排序、关键边和非法输入测试。
3. [x] EVM 和分日 PV、0/100 EV、零分母与返工成本测试。
4. [x] step 引擎、资源容量、工时/成本、持久 RNG、确定性重放。
5. [x] LMS 场景 fixture，包含缺陷修复与一次需求变更触发。
6. [x] 通过独立 LangGraph 模拟子工作流调用计算节点；相同 seed/输入/授权分配产生相同领域事件及指标。

## M4：五过程组与变更闭环（依赖 M3）

1. [x] Charter→SRS→WBS→计划审批→初始基准；产物可追踪。
2. [x] Developer–Tester 模拟反馈、修复上限、监控/风险与模拟日数上限退出。
3. [x] 正式变更提案、确定性影响分析、版本绑定审批、新基准事务提交。
4. [x] 测试拒绝、过期审批、基准不可变、历史指标不回写和幂等应用。
5. [x] 收尾前置校验、Sponsor 验收、项目总结与管理报告。
6. [x] 通过 API 运行 LMS Mock 场景，覆盖五过程组、六角色、返工和一次获批变更；中途重启仍完成。

## M5：React 与端到端验收（依赖 M4）

1. [x] React/TypeScript 工程、API 响应类型、项目配置和 run 控制；后端提供 OpenAPI，前端类型手工维护，并非自动生成。
2. [x] Agent 时间线、SSE 重连、人工审批表单、模拟模式标签。
3. [x] WBS/甘特/关键路径、进度与成本图、版本/变更记录。
4. [x] 结项报告及 MSPDI 导出；XML/字段/下载验证通过。本机未检测到 Microsoft Project，原生导入待具备环境时验证。
5. [x] 浏览器 E2E：无 Key 的 LMS 全程、Human 四次审批及拒绝路径、刷新恢复。
6. [x] 安装/演示文档、完整测试结果与限制，见 README.md 和 validation.md。

## 本次阶段记录

- M0：完成。
- M1：完成。执行 `.\.venv\Scripts\python.exe -m pytest -q`：**16 passed, 1 warning in 3.73s**。
- 测试覆盖：health/OpenAPI、创建/读取/列表、Human 模式配置、分页、10 组非法输入、文件库重建 app 后持久化、Task/Artifact 唯一约束、任务工期/成本约束、外键与事务回滚。
- 测试环境：Python 3.12.6，实际安装依赖版本保存至根目录 requirements-lock.txt。
- 非阻断告警：Starlette TestClient 提示当前 httpx 适配将弃用；后续升级测试依赖时迁移适配，不屏蔽告警。
- M2：完成骨架并测试；M3 计算与模拟纯函数开发中；M4—M5 尚未开始。
- 当前限制：无前端、无模拟推进、无基准审批或计算服务；真实模型 HTTP 适配经本地替身验证，未进行付费外部调用。
- M1 复核：补充 lifespan 的 finally 清理，初始化或运行异常时也释放数据库连接；pytest 再验为 16 passed，1 条相同依赖警告（3.02s）。
- 真实 HTTP 冒烟：独立启动 uvicorn，在临时 SQLite 上通过 health、创建项目和读取项目；结束后关闭测试进程，未占用常驻服务或修改演示数据库。


## M2 交付记录

- 测试：`python -m pytest -q --tb=short`，**26 passed in 8.46s**，本次无警告；依赖快照已更新。
- 新覆盖：六角色 Mock、固定路由、人工批准/拒绝、checkpoint 重建恢复、过期版本和重复审批、创建幂等、活动 run 冲突、SSE 游标重放、非法输出三次上限、任务引用和角色越权校验、M1 数据升级、业务提交后 checkpoint 前崩溃恢复、审批意图提交后进程重建、真实 provider HTTP 和缺失配置显式失败。
- 工作流只生成结构化提案；成功状态为 awaiting_m3，绝不将项目标为 completed，开发/测试产物为 not_executed。
- M2 固定 DAG 每节点一次，回执键为 (run,node)；M3 实现循环前必须加入逻辑迭代号。
- SQLite checkpointer 独立于业务数据库，回执与事件同事务；单进程串行命令锁，服务必须只启一个 worker。
- Alembic 0001 固定 M1，0002 新增工作流表；识别 M1 未版本化表并保留数据升级，未知字段结构拒绝自动接管。降级通过恢复备份。
- human 审批由 interrupt/Command 恢复，llm Sponsor 的审批调用所选 provider；拒绝后结束 M2 骨架。
- SSE 在暂停/失败/awaiting_m3 时发完事件关闭；resume 后客户端携带 Last-Event-ID 重连。
- 不保存无效原始模型输出或 provider 异常详情，防止回显密钥；保存有效输出、输入摘要、错误类型、尝试次数与耗时。
- 角色三次校验/调用失败后终结尝试，不因重复 resume 无限重试；配置缺失可修复后恢复，已耗尽尝试的人工重置策略留后续扩展。
- 下一阶段 M3：CPM、EVM、资源与模拟 tick；本次未实现。

### M2 恢复与审批补充复核

- 发现并修复：LLM Sponsor 审批原先直接调用 provider，缺少角色调用的审计和重试边界。现在所有模型决策（含审批）共用 validated_call，最多三次、版本校验、输入摘要一致性验证和成功输出持久化复用。
- 验证模型审批的版本错误三次后失败、不改变审批状态；显式 resume 不无限追加调用。
- 注入“模型决策已审计、业务审批尚未提交”的崩溃，恢复后复用已记录决策，模型审批调用次数仍为一次。
- 新增真实 OS 进程边界测试：第一个 Python 进程启动并暂停人工审批、退出；第二个独立进程读取同库/checkpoint、提交审批并完成 M2，前置角色不重复执行。
- 最新测试：`python -m pytest -q --tb=short`，**29 passed in 18.30s**，无警告。仍未实现 M3 及后续阶段。


## M3 进展（2026-11-18，尚未整体验收）

- 新增 services/planning.py：严格计划输入、FS/lag DAG CPM、所有关键边、5 日工作周映射、整数分 PV 与 0/100 EVM，保留 Decimal 比率及零分母原因。
- 新增 services/simulation.py：纯 step、资源容量、已验收前置与 lag、工时成本、模拟测试/返工、次数与日数上限、一次变更提案触发。随机状态可经过 JSON 存储再恢复，调用不修改原始快照。
- 新增 examples/library_management/scenario.json：四个 LMS 模块、资源及依赖、一次强制模拟缺陷、第三日的变更触发配置。
- 计算与引擎单元测试 19 项通过（0.15s）；最新完整套件 **48 passed in 18.19s**，无警告。
- LMS 纯引擎重放验证：无资源约束 CPM=4 天；单资源与返工后模拟=7 天，最终 PV=EV=30,000 分、AC=35,000 分；缺陷、修复、变更提案各一次，两次运行完全一致。
- 未完成：资源/依赖/tick/metric 数据库模型与迁移、LangGraph 调用这些服务、业务快照持久化及恢复集成测试。当前 API 仍停在 awaiting_m3；单元测试驱动纯引擎不代表完整 Agent 模拟闭环。
- 正式变更审批与基准更新属于 M4，当前提案事件不算完整变更管理。


### M3 持久化与工作流集成

- 新增 Alembic 0003、SimulationRun 与 SimulationTick。设计调整：M3 将资源与依赖保存在版本化不可变计划 JSON，将进度/RNG/分配/指标保存在唯一 (run,day) 记录，避免提前维护多套可变状态；M4 的批准基准将使用独立模型。
- 新增模拟 API：POST/GET /runs/{id}/simulation、POST /runs/{id}/simulation/resume。须先完成 M2 提案工作流；计划与场景一旦创建不能通过 API 覆盖。
- LangGraph initialize/tick/条件循环是唯一调度者，使用独立 thread_id。逐日快照、指标、事件在同一事务提交，恢复先读取已提交 tick 再推进；十进制比率存为字符串。
- 三项新集成测试覆盖完整 API 重放、SSE 顺序与变更去重、文件库重建、第三日业务提交但 checkpoint 缺失的恢复，以及输入/审批前置校验。
- 最新完整测试：**51 passed in 20.69s**，无警告。
- 当前边界：awaiting_m4、draft_unapproved；这是未批准计划的计算演示，尚非完整五过程组闭环，不能宣称正式变更已完成。
- 下一步 M4：将 Agent 规划产物转换为可审批计划，初始基准、变更影响与版本更新、Agent 开发测试反馈和收尾验收。
- 用户提供的真实模型配置已保存到 Git 忽略的本地 .env；已完成两类真实模型调用验证，报告不包含密钥。


## M4 进展：正式基准与变更事务基础（尚未整体验收）

- 新增 Baseline、ChangeRequest 和 Alembic 0004。基准包含计划、CPM、版本、前版本、审批证据、生效日和内容 hash。
- commit_baseline 校验项目/run 归属、明确的计划产物版本、批准结果、初始版本与生效日；后续基准必须关联当前源版本的正式变更。
- propose_change/analyze_change 确定性计算新增/删除/修改任务、BAC 和 CPM 工期差异；禁止改写已验收任务及其依赖；审批提交时重新验证影响分析。
- 重复相同请求返回原记录，冲突重放、过期源基准、未批准/拒绝审批、无正式变更的直接更新均被拒绝。
- SQLite triggers 阻止已批准基准 UPDATE/DELETE、版本化 Artifact UPDATE/DELETE、基准审批证据 UPDATE 和变更提案内容 UPDATE。状态及应用结果由事务服务更新。
- 测试覆盖初始审批绑定、完整获批变更事务、历史内容与 hash 保留、幂等应用、过期源、拒绝审批、改写已验收任务，以及直接 SQL 覆盖历史的拒绝。
- 尚未完成：将这些服务接入 LangGraph 的计划/变更审批节点；从模拟快照获得已验收任务与剩余工作；新基准分时 PV 衔接；Agent 反馈循环、验收和结项报告。当前 API 仍是 M3 草案模拟，不声称已实现五过程组闭环。
- 产物修订号与批准基准版本独立：首份计划被拒绝后，第 2 版产物仍可形成第 1 版正式基准；审批始终绑定具体产物修订号。
- 最新完整回归：**62 passed in 21.16s**，无警告；其中基准与变更事务测试 11 项。

### M4 正式审批图与 API 接入

- 新增 PlanApprovalWorkflow：Sponsor 决策节点 → apply_decision 事务节点；独立持久 thread、Human interrupt/Command、LLM 校验审计、审批意图保存与幂等回执。
- 新增 plan-approvals 提交/查询/decision/resume，以及 baselines、changes 只读查询。初始计划和正式变更共用审批图，影响分析来自 Python 服务。
- 已测试 Mock 初始审批→获批变更→两版基准与影响记录；Human 重启后拒绝、修订、批准；重复/过期决策；基准提交后 checkpoint 缺失的恢复。
- 草案模拟新增审批守卫：已有正式审批时，未批准或拒绝的初始计划不得执行；有正式基准时只能使用批准计划，不能从模拟 API 绕过变更更新范围。
- 完整套件 **65 passed in 24.64s**；新增历史查询后审批 API 定向测试 **3 passed in 3.93s**。所有测试使用 Mock，无额外外部模型调用。
- 仍未完成：从 Agent 规划产物生成计划、模拟触发变更后自动进入审批图、按新基准继续剩余工作与分时 PV 衔接、执行阶段 Agent 反馈及结项验收。M4 尚未标记完成。


### M4 运行中变更与新基准续跑

- Scenario.formal_management 显式启用正式管理；启动必须存在匹配的初始批准基准。草案模式仍保留用于独立计算演示。
- LangGraph tick 路由接入 prepare_change/review_change。固定 LMS 教学请求生成一次逾期提醒任务、确定性成本和依赖，创建正式变更与审批图输入；human 模式暂停父模拟和审批图，审批后显式恢复。
- 批准后迁移剩余任务状态并使用新基准继续；拒绝则标记变更已处理、按原范围继续。未通过迁移节点的外部基准切换会被阻止。
- rebaseline 服务保留工时、AC、验收日、RNG；禁止移除或原地重估已开工任务。未来 PV 从历史累计 PV 锚点起均匀分配剩余 BAC，假设与依赖预测区间随快照保存，历史 tick 和指标不回写。
- 5 项新增测试：自动批准后 9 日完成新范围；human 批准/拒绝两条路径在文件库重建后恢复；开工状态与 PV 锚点保护；基准迁移事务提交后 checkpoint 缺失的幂等恢复。
- 最新完整回归 **70 passed in 34.08s**，无警告，无外部模型调用。
- 剩余：初始计划由 Agent 产物生成、PM 动态变更提案、执行阶段 Developer–Tester 角色决策反馈、Sponsor 最终验收与报告，以及 M5 前端。M4 仍未完成。


### M4 执行阶段角色反馈与最终验收

- AgentContext 增加 operation/facts。Developer 的 develop/repair 动作必须与授权任务和返工事实一致；Tester 报告必须逐项匹配引擎模拟结果；Progress & Cost Analyst 解释确定性指标并提示风险。每个模拟日按角色/操作生成唯一执行记录，重放复用已验证决策。
- formal_management 模式在 tick 提交前完成角色校验。伪造测试通过的模型输出会在三次尝试后失败，当天工时/成本/进度不提交；下一日 Developer 能看到已有失败所需返工。
- Scenario.final_acceptance 显式启用最终验收，必须配合 formal_management。LangGraph 在范围完成后进入准备报告→Sponsor 验收→归档，只有验收批准才标记项目和 run 为 completed。
- 收尾检查全范围覆盖、无开放阻断缺陷、活动基准匹配、无未处理计划/变更。PM 给出结构化结项建议，Sponsor 仍需审批指定报告产物版本。
- Human 最终验收通过 /simulation/acceptance 提交；未提交决策不能直接 resume。拒绝返回 acceptance_rejected，保留未完成状态和审阅理由，不自动宣称成功。
- /simulation/report 返回候选或最终 JSON 管理报告及验收状态，包括模拟日、范围验收、测试次数、EVM、基准/变更历史、seed/场景/引擎/provider 版本、管理经验和模拟限制。候选与最终报告均为不可覆盖的独立 Artifact。
- 新增 4 项测试：Mock 全执行反馈与结项；human 批准/拒绝两条路径重启恢复；不诚实 Tester 无法提交伪结果或提前结项。
- 完整回归 **74 passed in 43.07s**；完善报告 provider 元数据和 Mock v2 后收尾定向测试 **4 passed in 8.96s**。Mock v2 区分最终模拟验收与一般提案的审批理由。
- M4 剩余：从需求/估算 Agent 产物自动生成审批计划、让 PM 参与动态变更提案；目前计划仍由调用者显式提交，教学新增范围仍为固定场景。M5 尚未开始，总体 Goal 未完成。


### M4 验收：自动规划、PM 变更和顶层交付图

- Requirements WorkItem 记录前置依赖和验收标准；Mock v3 为 Library 项目输出四个具体模块的 SRS/WBS，非 Library 项目仍使用通用 Mock 范围。
- Progress & Cost Analyst 的 estimate_plan 输出逐任务工期与资源费率假设；plan_builder 校验完整覆盖，确定性计算 duration × resource daily rate 的成本，并运行 CPM 校验。
- PM 的 propose_change 输出新增任务、资源、工期、前置依赖和验收标准。模型无权指定最终成本或更新基准；代码按费率计算、验证可迁移性后进入正式审批。change_spec 独立持久化并作为审批证据传入 Sponsor。
- DeliveryWorkflow 是顶层 StateGraph，协调启动角色图、自动规划、计划审批、正式模拟与验收；各子图通过稳定 thread_id、共享项目产物及事务回执协作，PM 不调度节点。
- 新入口 POST /projects/{id}/delivery（Idempotency-Key），GET /runs/{id}/delivery，POST /runs/{id}/delivery/resume；GET /runs/{id}/artifacts 提供产物审阅。
- 4 项新增测试覆盖：无 Key 的 LMS 自动完成且服务重建后结果不变；Human 四个审批点逐次重建 app 后恢复；拒绝章程不创建计划或模拟；不完整估算三次失败后不能创建基准。
- 报告增加需求/change_spec 引用及每个最终任务的验收标准；范围缺少验收标准时不能结项。
- 最新完整回归 **78 passed in 49.13s**，无警告，无外部模型调用。LMS Mock：9 模拟日、EV=40,000 分、AC=45,000 分、两版正式基准、一次获批变更、一次缺陷修复与最终 Sponsor 验收。
- M4 后端验收完成。尚未交付 M5 的 React 可视化、Microsoft Project 导出与浏览器 E2E；总体 Goal 保持 active，不能以 API 闭环代替最终 Web 验收。

## M5 最终交付与复核

- React + TypeScript + Vite Dashboard 完成五个页面：总览、范围/计划、协作/轨迹、变更/审批、报告。展示六角色、五过程组、历史模拟日、指标曲线、关键路径、WBS/甘特和版本化产物。支持 Mock 快捷启动、实验配置、项目重开、人工审批及刷新恢复。
- SSE 保存游标重连、去重并可展开全部事件；移动端 390px 无横向溢出。桌面与移动截图保存在 docs/screenshots。
- 新增批准基准的 MSPDI 导出；测试日历、稳定 UID、依赖/lag、成本和只读版本查询，浏览器真实下载并解析 XML。本机无 Project 注册项，原生导入未验证。
- 最终审计补齐 PM 合法优先级分配/容量守卫、章程约束/干系人、需求与变更验收标准传递、Analyst 偏差/关键路径解释、prompt_version 持久化迁移，以及审批绑定的剩余计划/PV 锚点/源快照完整性。
- 完整后端测试：**88 passed in 61.80s**；前端 TypeScript/生产构建通过；浏览器 E2E **3 passed**，覆盖 Mock 完整闭环、Human 四审批点及拒绝章程。最后截图调整后的 E2E 状态仍为 passed。
- 独立入口冒烟通过：实际启动 python -m app.serve，使用临时数据库验证生产 UI、完整 Mock 交付、最终报告及 MSPDI 下载；停止自有测试进程。
- README、architecture.md 和 validation.md 已更新。真实模型配置保存在本地忽略文件，验证边界仍为模型发现、Sponsor 与审批输出，不声称完整真实模型流程已外部通过。
- 当前功能达到 Mock Web 最终验收；真实 LMS 代码执行、多用户部署以及原生 Project 导入验证作为后续扩展/环境验证保留。
