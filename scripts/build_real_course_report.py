"""Append the measured real API experiment to the team's existing Word report."""
import json,collections
from pathlib import Path
from datetime import datetime,timedelta,timezone
from docx import Document
from PIL import Image
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
root=Path(__file__).resolve().parents[1]
evidence=root/'output'/'real-ticketing'
load=lambda name:json.loads((evidence/(name+'.json')).read_text(encoding='utf-8'))
m=load('manifest')
assert m['success'],'Do not publish an incomplete run as success'
r=load('report')['report']; traces=load('traces'); bases=load('baselines'); changes=load('changes'); approvals=load('approvals'); sim=load('simulation')
source=root/'docs'/'report'/'软件项目管理实验报告_方宇鹄小组.docx'
target=source.with_name('软件项目管理实验报告_方宇鹄小组_真实API双变更版.docx')
d=Document(source)
# Preserve original mock experiment and the team's earlier verification record.
p=d.paragraphs[4];p.text='图书管理 Mock 对照与校园活动票务真实模型双变更实验'
insert=d.paragraphs[58].insert_paragraph_before('本版补充说明　原报告第一至十章保留小组既有实验及验证记录；新增第十一章记录 2026 年 11 月 24 日实际运行的 qwen3.7-flash 校园活动票务实验，包含两次独立批准变更和三版基准。新增结论以本次保存的调用、审批与逐日数据为依据，不能与原图书管理案例的数值或此前模型验证混用。')
new=[]
def paragraph(text,style=None):
 p=d.add_paragraph(text,style);new.append(p._p)
 p.paragraph_format.space_after=Pt(7)
 return p

def heading(text,level):
 p=paragraph(text,'Heading '+str(level));p.paragraph_format.keep_with_next=True
 return p

def table(headers,rows,widths=None):
 t=d.add_table(rows=1,cols=len(headers));new.append(t._tbl)
 t.autofit=False
 if widths:
  available=(d.sections[-1].page_width-d.sections[-1].left_margin-d.sections[-1].right_margin)/360000
  factor=min(1,available/sum(widths))
  widths=[w*factor for w in widths]
  for col,w in zip(t.columns,widths): col.width=Cm(w)
 for i,text in enumerate(headers):t.rows[0].cells[i].text=str(text)
 repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
 for row in rows:
  cells=t.add_row().cells
  for i,text in enumerate(row):cells[i].text=str(text)
 for ri,row in enumerate(t.rows):
  for ci,cell in enumerate(row.cells):
   if widths:cell.width=Cm(widths[ci])
   tcpr=cell._tc.get_or_add_tcPr();borders=OxmlElement('w:tcBorders')
   for edge in ['top','left','bottom','right']:
    e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
   tcpr.append(borders)
   shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'E8EEF5' if ri==0 else ('F7F9FB' if ri%2==0 else 'FFFFFF'));tcpr.append(shade)
   for p in cell.paragraphs:
    p.paragraph_format.space_after=Pt(4);p.paragraph_format.space_before=Pt(4)
    if ri==0:p.paragraph_format.keep_with_next=True
    for run in p.runs:
     run.font.size=Pt(10.5);run.font.name='宋体';run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体');run.bold=ri==0
 return t
money=lambda cents:f"¥{int(cents)/100:,.2f}"
roles={'sponsor':'发起人','project_manager':'项目经理','requirements_analyst':'需求分析师','developer':'开发工程师','tester':'测试工程师','progress_cost_analyst':'进度成本分析师'}
heading('十一 校园活动票务真实模型双变更实验',1)
paragraph(f"我们使用 qwen3.7-flash 完成校园活动票务平台的受控多智能体项目管理实验。本次实际发送 {m['real_api_calls']} 次模型 API 请求，六个角色均产生经校验的输出；两次变更分别审批并更新为 V2、V3 基准，最终通过发起人验收。项目共推进 {r['simulation_days']} 个模拟工作日。模型请求是真实网络调用，开发、测试、退款及核销结果仍由教学模拟引擎产生，没有执行真实票务代码或支付。")
heading('11.1 场景和实验设置',2)
paragraph('初始范围为活动发布、报名与名额、支付沙箱、电子票、在线核销及联调验收六个模块。相较四模块图书案例，该场景呈现从活动配置到票据核销的业务依赖，联调失败需要开发修复；退款与离线核销作为初始范围之外的新需求，分别触发正式变更。初始任务粒度、资源容量及费率由实验简报约束，模型在这些边界内分解依赖、说明验收标准并作出管理决策。')
start=datetime.fromisoformat(m['started_at']).astimezone(timezone(timedelta(hours=8)))
finish=datetime.fromisoformat(m['finished_at']).astimezone(timezone(timedelta(hours=8)))
table(['设置','本次取值'],[['模型',m['model']],['API协议','OpenAI兼容 chat/completions；JSON结构化输出'],['模式','real模型 / LLM发起人 / simulation项目执行 / seed 42'],['实际起止时间',f"{start:%Y-%m-%d %H:%M:%S} 至 {finish:%Y-%m-%d %H:%M:%S}（北京时间）"],['运行ID',m['run_id']],['API请求与角色审计',f"{m['real_api_calls']} 次HTTP调用；{len(traces)} 条校验审计；不启用Mock回退"]],[3.6,12.4])
heading('11.2 六角色交互和初始计划',2)
paragraph('发起人提出需求后，项目经理形成章程，发起人审批；需求分析师给出任务与标准，绩效分析师给出估算，再由确定性服务计算预算与CPM。执行时项目经理选择可行任务，开发提交授权动作，测试解释引擎证据，绩效分析师说明每日偏差；变更和最终结项均回到发起人审批。')
counts=collections.Counter(t['role'] for t in traces if t['valid'])
table(['角色','有效审计数','本次交互证据'],[[roles[role],counts[role],{'sponsor':'需求、章程/计划/两次变更/最终验收审批','project_manager':'章程、逐日派工、两次变更提案和结项建议','requirements_analyst':'六项初始任务、依赖与验收标准','developer':'逐日执行及已知缺陷修复','tester':'模拟测试结论、缺陷反馈与回归','progress_cost_analyst':'任务估算、关键路径及每日绩效解释'}[role]] for role in roles],[3.2,2.1,10.7])
initial=bases[0]['content']['plan'];last=bases[-1]['content']['plan']
table(['ID','初始任务','工期','资源','前置'],[[t['id'],t['title'],t['duration_days'],t['resource_id'],','.join(e['predecessor'] for e in initial['dependencies'] if e['successor']==t['id']) or '—'] for t in initial['tasks']],[1,6.5,1.3,2.5,4.7])
heading('11.3 两次正式变更及基准演进',2)
# Sort changes by their applied baseline version, not UUID/API order.
version={b['id']:b['version'] for b in bases}
changes=sorted(changes,key=lambda c:version.get(c['applied_baseline_id'],999))
for i,change in enumerate(changes,1):
 impact=change['impact'];b=next(b for b in bases if b['id']==change['applied_baseline_id'])
 heading(f'CR 0{i} '+('活动退款申请与审批' if i==1 else '离线验票与重复核销防护'),3)
 paragraph('模型提案理由：'+change['reason'])
 paragraph(f"确定性影响分析：新增任务 {', '.join(impact['added_task_ids'])}，预算增加 {money(impact['delta_bac_cents'])}，依赖网络工期变化 {impact['delta_duration_days']} 日。审批状态为 {change['status']}，形成 V{b['version']}，生效边界为已完成第 {b['effective_day']} 日之后。")
 a=next(a for a in approvals if a['target_id']==change['artifact_id'])
 paragraph('发起人审批意见：'+a['decision']['reason'])
 paragraph('审批同时绑定计划产物版本、源执行快照、剩余预测与PV锚点；批准后继续已有工作，保留投入成本、验收日和历史指标。第二次变更独立使用回执和审批，未复用第一次的批准结果。')
table(['基准','生效边界日','任务数','BAC','CPM网络工期'],[[f"V{b['version']}",b['effective_day'],len(b['content']['plan']['tasks']),money(sum(t['budget_cents'] for t in b['content']['plan']['tasks'])),b['content']['schedule']['duration_days']] for b in bases],[1.5,2.4,1.8,4.3,6])
heading('11.4 执行监控与测试返工',2)
paragraph('引擎预设末项初次模拟测试失败，以保证可观察的开发与测试反馈循环。失败是实验输入，不能归因于真实模型写出了缺陷代码。失败后开发角色收到已知缺陷并提交修复动作，测试角色回归；修复增加实际模拟成本，不重复产生挣值。CPM仅描述依赖网络，不含资源等待和返工。')
table(['模拟日','基准','PV','EV','AC','SPI','CPI'],[[v['status_day'],f"V{v['baseline_version']}",money(v['pv_cents']),money(v['ev_cents']),money(v['ac_cents']),str(v['spi'] or '未定义')[:6],str(v['cpi'] or '未定义')[:6]] for v in sim['metrics']],[1.4,1.3,2.6,2.6,2.6,2.7,2.8])
for filename,caption in [('real-overview.png','图11-1 真实模型实验的模拟执行总览'),('real-changes.png','图11-2 两次正式变更及三版批准基准')]:
 image=evidence/filename
 if image.exists():
  p=paragraph('');p.add_run().add_picture(str(image),width=Cm(min(15.2,17*Image.open(image).width/Image.open(image).height)))
  paragraph(caption)
heading('11.5 最终结果与证据边界',2)
f=r['final_metrics']
paragraph(f"本次最终BAC为 {money(f['bac_cents'])}，PV为 {money(f['pv_cents'])}，EV为 {money(f['ev_cents'])}，AC为 {money(f['ac_cents'])}；SPI={float(f['spi']):.3f}，CPI={float(f['cpi']):.3f}。最终范围包含 {len(r['scope_acceptance'])} 项任务，两次变更均已应用。发起人针对最终候选报告版本作出批准，系统才将项目归档为完成。")
paragraph('绩效分析师的实际解释：'+r['performance_analysis']['assessment'])
paragraph('证据保存在 code/output/real-ticketing：api-calls.jsonl 记录网络调用时间与结果；traces.json 保存模型输出及校验；approvals.json 保存目标版本与意见；baselines.json、changes.json、simulation.json、report.json 保存管理事实；plan-v1.xml至plan-v3.xml为批准计划导出。demo.db与demo.checkpoints.db应一起保留。以上文件不包含密钥。')
paragraph('本次票务运行在第三日执行时也曾因连续三次无效证据引用而停止。我们将模型引用字段收紧为空列表，来源关联仍由系统保存的产物ID与输入hash承担；随后通过一条明确记录的修复命令，在同一checkpoint上开启新的、仍以三次为上限的恢复批次。原失败轨迹不删除，审批不重做，成本不清零。failure-before-recovery.json及explicit_provider_repair1回执保存了中断和修复依据。')
paragraph('原报告中的图书案例和此前模型运行属于对照材料，其Project截图不能作为本次票务V3的导入证据。本次另提供三版XML；若未另行导入并截图，不声称本次票务计划已在Microsoft Project中验证。真实模型输出具有不确定性，再次调用不保证相同WBS或指标；答辩可回放本次已保存轨迹。')
heading('11.6 真实调用中发现的问题',2)
paragraph('首次尝试发送18次真实请求，在第二日PM派工节点连续三次未通过业务校验后停止；当天进度和成本没有提交。失败尝试保存在real-ticketing-attempt1-failed，不计为完成实验。修复为在既有三次调用上限内，将校验原因反馈给下一次真实模型请求，同时明确可选任务与资源容量约束；没有修改引擎事实、放宽校验或用Mock替代。第二次尝试发送10次请求，但发起人将依赖网络计划误认为资源平衡排程并拒绝初始计划，记录保存在real-ticketing-attempt2-rejected。我们随后在审批证据中明确：effective_day是基准边界，不是所有任务的开工日；同资源任务由逐日派工串行执行。没有覆写拒绝结果，第三次尝试发送7次请求，初始估算提案连续校验失败而停止；另一次针对性真实诊断返回了有效输出。我们进一步区分初始总量估算与逐任务估算的操作指令，并另开实验。前述尝试均保留，本文结果只取最终完成的独立运行；不可把失败尝试的调用数混入最终运行。')
heading('11.7 复现与答辩演示',2)
paragraph('在 code 目录运行启动真实汇报.ps1，打开 http://127.0.0.1:8000，在当前项目列表选择校园活动票务平台。查看总览、协作与轨迹、变更与审批、结项报告。该操作读取真实调用留下的历史，不重新调用模型。若需重新运行，使用 scripts/run_real_course_demo.py，提供本地配置和新的输出目录；会产生新的API费用与不确定输出，不能覆盖原证据。')
paragraph('为支持本次实验，平台新增顺序变更请求，以及按变更编号隔离的幂等回执；保留旧单变更场景。针对性测试覆盖两次变更形成三版基准、服务重启后的结果保持、人工逐次审批后重启恢复，以及显式修复批次保留原失败记录且成本不重复。平台软件测试与被模拟票务业务测试分开记录。')
# Insert the new chapter before existing appendices, preserving their content.
anchor=next(p._p for p in d.paragraphs if p.text.startswith('附录 A') and p.style.name=='Heading 1')
for el in new:anchor.addprevious(el)
# The original template uses page-break-before on major headings; enforce for this chapter.
first=new[0]
pr=first.get_or_add_pPr();pr.append(OxmlElement('w:pageBreakBefore'))
d.save(target)
print(target)
