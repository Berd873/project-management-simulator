# 组员交接

本次更新为校园活动票务真实API双变更实验。六角色调用qwen3.7-flash，56次请求、47条有效决策；8个模拟工作日、两次批准变更、三版基准。包含一次保留失败轨迹的显式修复恢复。API调用真实，开发测试成果为模拟。

## 拉取与运行

在仓库根目录执行：

```powershell
git pull --ff-only origin main
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
cd frontend
pnpm install --frozen-lockfile
pnpm run build
cd ..
.\.venv\Scripts\python.exe scripts/serve_course_demo.py
```

需要Python 3.12+、Node.js 24、pnpm 11.25.0。安装完成也可双击启动真实汇报.cmd，不受PowerShell脚本执行策略影响。访问 http://127.0.0.1:8000/?run=29cf01fc-e98a-4736-9601-86e05d7139c0 。前端dist需自行构建，源码仓库不提交依赖和dist。

首次启动从examples/campus_ticketing/replay.zip还原SQLite业务库及checkpoint；不会覆盖现有数据库，也不会重新调用模型。查看范围与计划、协作与轨迹、变更与审批、结项报告。

## 接续工作

- 前端：可将票务场景加入新建实验预设，完善有效决策与失败尝试的区分。
- 项目计划：导入docs/evidence/campus-ticketing/plan-v3.xml，核对新案例并制作Project截图；旧图书案例截图不可作为新案例证据。
- 报告：当前组员报告保留在docs/report；真实实验事实、审批、指标和截图在docs/evidence/campus-ticketing。此前另存的真实API双变更版Word/PDF已不在当前工作区，本次不重建或覆盖组员报告。
- 后端：新增scheduled_changes支持顺序变更；原单变更兼容；repair_nodes只用于显式修复操作，不应对外自动重置失败上限。

此前验证93项后端测试通过。重新运行pytest时可将TEMP/TMP指定为D盘临时目录。密钥和.env不随仓库共享；重跑真实API需各自配置，不能覆盖本次证据。回放文件已检查不含本地API Key。
