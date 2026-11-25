> 仓库交接更新：回放请使用 scripts/serve_course_demo.py 或启动真实汇报.cmd；证据见 docs/evidence/campus-ticketing。下文保留原交付包操作记录，其中另存的Word/PDF目前已不在工作区，具体以 handoff.md 为准。

# 真实模型双变更课程实验

模型 qwen3.7-flash；运行ID `29cf01fc-e98a-4736-9601-86e05d7139c0`。最终完成并获Sponsor验收。API调用真实，票务开发、测试、退款和核销仍为教学模拟。

- 本运行56次实际请求，47条有效决策，9条未通过校验；包含一次保留原失败记录的显式修复恢复。
- 8个模拟工作日，8项最终任务，两次批准变更，V1/V2/V3三版基准。
- BAC=PV=EV=560000分（¥5600）；AC=620000分（¥6200）；SPI=1；CPI约0.903。
- 后端93项测试通过；实际网页读取运行及三版基准检查通过，截图保存在output/real-ticketing。

在code目录运行 `启动真实汇报.ps1`，打开 http://127.0.0.1:8000/?run=29cf01fc-e98a-4736-9601-86e05d7139c0 。这是读取已保存的真实调用记录，不会重新调用模型。

报告为实验报告目录中的“软件项目管理实验报告_方宇鹄小组_真实API双变更版.docx”和同名PDF。原报告保留；新增第十一章，含两次变更、指标、调用审计、失败尝试和修复恢复。旧图书管理Project截图不是本次新案例的导入证据；本次三版XML另存，未声称本次已验证原生Project导入。

证据位于output/real-ticketing；demo.db及demo.checkpoints.db一起保留。manifest.json记录起止时间，api-calls.jsonl记录请求，traces.json记录输出与校验，approvals.json记录审批，baselines/changes/simulation/report.json记录管理事实。failure-before-recovery.json及explicit_provider_repair1回执记录显式恢复。前三次失败/拒绝尝试保存在相邻attempt目录，不计入本运行56次请求；另有一次针对性真实诊断调用。

重跑使用 `scripts/run_real_course_demo.py --config 本地.env路径 --output 新目录`，需要真实API配置，具有费用和输出不确定性；不要覆盖原证据。`--resume-repaired`仅用于代码修正后的单次显式恢复，不删除旧失败记录，仍限定最多三次。

测试临时目录改用D盘：先将TEMP/TMP设为本项目output/temp，再运行pytest。密钥仅从本地环境配置读取，不在报告或证据中记录。
