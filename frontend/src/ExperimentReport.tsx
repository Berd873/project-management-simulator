import { useEffect, useState } from 'react'
import { money, ratio } from './api'
import type { Project, RunData } from './api'

type Member = { name: string; studentId: string; responsibility: string }
type Notes = { members: Member[]; reflection: string }
const emptyMember = (): Member => ({ name: '', studentId: '', responsibility: '' })
const roleRows = [
  ['发起人', '需求与待审产物', '需求简述、审批意见', '向项目经理提出需求，批准章程、基准、变更和结项'],
  ['项目经理', '需求、计划和执行快照', '章程、分配、变更与收尾建议', '协调需求、执行和发起人决策'],
  ['需求分析师', '已批准章程', '范围、WBS、验收标准', '将任务交给估算与执行角色'],
  ['开发工程师', '已授权任务与缺陷', '模拟开发与修复动作', '将模拟交付交给测试工程师'],
  ['测试工程师', '任务验收标准与模拟事件', '模拟测试与回归结论', '将缺陷反馈给开发与项目经理'],
  ['绩效分析师', 'WBS、资源和每日指标', '估算、关键路径与偏差分析', '为计划审批及监控提供依据'],
]

export default function ExperimentReport({ data, project, run, onClose }: { data: RunData; project: Project; run: string; onClose: () => void }) {
  const [notes, setNotes] = useState<Notes>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(`pm-report-${run}`) || 'null') as Notes | null
      if (saved?.members?.length === 4) return saved
    } catch { /* Use empty fields when local notes are invalid. */ }
    return { members: Array.from({ length: 4 }, emptyMember), reflection: '' }
  })
  const [images, setImages] = useState<{ wbs: string; gantt: string }>({ wbs: '', gantt: '' })
  useEffect(() => { localStorage.setItem(`pm-report-${run}`, JSON.stringify(notes)) }, [notes, run])
  const report = data.report?.report
  const charter = data.artifacts.find(a => a.kind === 'project_manager')?.payload
  const specification = data.artifacts.find(a => a.kind === 'requirements_analyst')?.payload
  const baseline = data.baselines.at(-1)
  const initial = data.baselines[0]
  const tasks = baseline?.content.plan.tasks || []
  const schedule = baseline?.content.schedule
  const strings = (value: unknown) => Array.isArray(value) ? value.map(String) : []
  const setMember = (index: number, field: keyof Member, value: string) => setNotes(previous => ({ ...previous,
    members: previous.members.map((member, i) => i === index ? { ...member, [field]: value } : member) }))
  const addImage = (field: 'wbs' | 'gantt', file?: File) => {
    if (!file) { setImages(previous => ({ ...previous, [field]: '' })); return }
    const reader = new FileReader()
    reader.onload = () => setImages(previous => ({ ...previous, [field]: String(reader.result || '') }))
    reader.readAsDataURL(file)
  }
  const complete = notes.members.some(m => m.name && m.studentId) && !!images.wbs && !!images.gantt
  return <div className="report-editor">
    <div className="report-toolbar"><button className="button light" onClick={onClose}>← 返回工作台</button><span>{complete ? '封面与 Project 截图已填写' : '提交前填写成员信息，并上传 Microsoft Project 截图'}</span><button className="button dark" onClick={() => window.print()}>打印 / 保存 PDF</button></div>
    <div className="report-fields"><div><h2>封面与分工</h2>{notes.members.map((member, index) => <div className="member-fields" key={index}><input aria-label={`成员${index + 1}姓名`} placeholder={index === 0 ? '组长姓名' : `组员${index}姓名`} value={member.name} onChange={e => setMember(index, 'name', e.target.value)}/><input aria-label={`成员${index + 1}学号`} placeholder="学号" value={member.studentId} onChange={e => setMember(index, 'studentId', e.target.value)}/><input aria-label={`成员${index + 1}分工`} placeholder="具体任务" value={member.responsibility} onChange={e => setMember(index, 'responsibility', e.target.value)}/></div>)}</div><div><h2>Project 证据与反思</h2><label>Microsoft Project WBS 截图<input aria-label="上传 WBS 截图" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => addImage('wbs', e.target.files?.[0])}/></label><label>Microsoft Project 甘特图截图<input aria-label="上传甘特图截图" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => addImage('gantt', e.target.files?.[0])}/></label><label>小组经验与反思<textarea aria-label="小组经验与反思" rows={4} value={notes.reflection} onChange={e => setNotes(previous => ({ ...previous, reflection: e.target.value }))}/></label></div></div>
    <article className="print-report">
      <header className="report-cover"><span>软件项目管理小组实验</span><h1>{project.name}</h1><p>多智能体软件项目管理模拟报告</p><dl><dt>实验模式</dt><dd>{project.llm_mode === 'mock' ? 'Mock 角色决策' : '真实模型角色决策'} / {project.sponsor_mode === 'human' ? '人工发起人审批' : '自动审批'}</dd><dt>模拟编号</dt><dd>{run}</dd><dt>模拟结果</dt><dd>{data.report?.accepted ? '完成最终验收' : '尚未完成最终验收'}</dd></dl><table><thead><tr><th>身份</th><th>姓名</th><th>学号</th></tr></thead><tbody>{notes.members.map((member, index) => <tr key={index}><td>{index === 0 ? '组长' : '组员'}</td><td>{member.name || '待填写'}</td><td>{member.studentId || '待填写'}</td></tr>)}</tbody></table></header>
      <section><h2>一 项目章程</h2><p><b>项目需求：</b>{project.description}</p><h3>项目目标</h3><ul>{strings(charter?.objectives).map((text, i) => <li key={i}>{text}</li>)}</ul><h3>成功标准</h3><ul>{strings(charter?.success_criteria).map((text, i) => <li key={i}>{text}</li>)}</ul><h3>约束与干系人</h3><p>{strings(charter?.constraints).join('；')}</p><p>{strings(charter?.stakeholders).join('、')}</p></section>
      <section><h2>二 多智能体组织与交互</h2><table><thead><tr><th>角色</th><th>输入</th><th>输出</th><th>交互关系</th></tr></thead><tbody>{roleRows.map(row => <tr key={row[0]}>{row.map((cell, i) => <td key={i}>{cell}</td>)}</tr>)}</tbody></table><p>发起人提出需求与审批意见；项目经理组织分析、估算、执行和监控；各角色输出经结构化校验后写入版本化产物与执行记录。</p></section>
      <section><h2>三 五大过程组</h2><table><thead><tr><th>过程组</th><th>本次模拟活动与证据</th></tr></thead><tbody><tr><td>启动</td><td>发起人需求、项目章程及章程审批</td></tr><tr><td>规划</td><td>需求规格、验收标准、WBS、工期与成本估算、初始基准批准</td></tr><tr><td>执行</td><td>逐日分配、模拟开发、缺陷修复和测试回归</td></tr><tr><td>监控与控制</td><td>每日 PV/EV/AC、关键路径分析、正式变更与新基准</td></tr><tr><td>收尾</td><td>范围核验、结项报告与发起人最终验收</td></tr></tbody></table><h3>逐日执行与监控记录</h3><table><thead><tr><th>工作日</th><th>任务与事件</th><th>PV</th><th>EV</th><th>AC</th></tr></thead><tbody>{data.simulation?.ticks.filter(t => t.day > 0).map(tick => { const metric = data.simulation?.metrics.find(m => m.status_day === tick.day); return <tr key={tick.day}><td>第 {tick.day} 日</td><td>{tick.assignments.map(id => tasks.find(t => t.id === id)?.title || id).join('、') || '等待'}；{tick.events.map(e => String(e.kind)).join('、') || '无事件'}</td><td>{metric ? money(metric.pv_cents) : '—'}</td><td>{metric ? money(metric.ev_cents) : '—'}</td><td>{metric ? money(metric.ac_cents) : '—'}</td></tr> })}</tbody></table></section>
      <section><h2>四 范围与进度管理</h2><p><b>范围之外：</b>{strings(specification?.out_scope).join('；')}</p><table><thead><tr><th>WBS</th><th>任务</th><th>工期</th><th>预算</th><th>前置任务</th><th>关键任务</th></tr></thead><tbody>{tasks.map(task => <tr key={task.id}><td>{task.id}</td><td>{task.title}</td><td>{task.duration_days} 日</td><td>{money(task.budget_cents)}</td><td>{baseline?.content.plan.dependencies.filter(d => d.successor === task.id).map(d => d.predecessor).join('、') || '无'}</td><td>{schedule?.critical_task_ids.includes(task.id) ? '是' : '否'}</td></tr>)}</tbody></table><p>初始计划工期 {initial?.content.schedule.duration_days ?? '—'} 个工作日；最终批准计划 CPM 工期 {schedule?.duration_days ?? '—'} 个工作日。CPM 不包含资源等待与返工。</p></section>
      <section className="report-evidence"><h2>五 Microsoft Project 计划证据</h2><h3>WBS</h3>{images.wbs ? <img src={images.wbs} alt="Microsoft Project WBS 截图"/> : <p>待上传 Microsoft Project WBS 截图</p>}<h3>甘特图</h3>{images.gantt ? <img src={images.gantt} alt="Microsoft Project 甘特图截图"/> : <p>待上传 Microsoft Project 甘特图截图</p>}</section>
      <section><h2>六 成本与绩效管理</h2>{report ? <><table><thead><tr><th>指标</th><th>最终值</th><th>含义</th></tr></thead><tbody><tr><td>PV</td><td>{money(report.final_metrics.pv_cents)}</td><td>计划价值</td></tr><tr><td>EV</td><td>{money(report.final_metrics.ev_cents)}</td><td>已验收工作价值</td></tr><tr><td>AC</td><td>{money(report.final_metrics.ac_cents)}</td><td>模拟实际成本</td></tr><tr><td>SPI</td><td>{ratio(report.final_metrics.spi)}</td><td>EV / PV</td></tr><tr><td>CPI</td><td>{ratio(report.final_metrics.cpi)}</td><td>EV / AC</td></tr></tbody></table><p>{report.performance_analysis?.assessment}</p></> : <p>模拟尚未形成结项指标。</p>}</section>
      <section><h2>七 变更管理</h2>{data.changes.length ? data.changes.map((change, i) => <div key={change.id}><h3>CR-{String(i + 1).padStart(2, '0')} {change.reason}</h3><p>状态：{change.status === 'applied' ? '已批准并应用' : change.status}；预算变化：{money(change.impact.delta_bac_cents)}；CPM 工期变化：{change.impact.delta_duration_days} 日；新增任务：{change.impact.added_task_ids.join('、')}。</p><p>源基准和批准后的新基准均保留；变更前历史指标不回写。</p></div>) : <p>尚无正式变更记录。</p>}</section>
      <section><h2>八 收尾与反思</h2>{report ? <><p>模拟历时 {report.simulation_days} 个工作日；{data.report?.accepted ? '发起人已完成最终验收。' : '最终验收尚未通过。'}</p><table><thead><tr><th>任务</th><th>验收日</th><th>模拟测试次数</th><th>验收标准</th></tr></thead><tbody>{report.scope_acceptance.map(task => <tr key={task.task_id}><td>{task.title}</td><td>第 {task.accepted_day} 日</td><td>{task.simulated_test_attempts}</td><td>{task.acceptance_criteria.join('；')}</td></tr>)}</tbody></table><ul>{report.management_lessons.map((lesson, i) => <li key={i}>{lesson}</li>)}</ul></> : <p>结项报告尚未生成。</p>}<h3>小组经验与反思</h3><p>{notes.reflection || '待填写小组经验与反思。'}</p><h3>组员分工</h3><table><thead><tr><th>成员</th><th>学号</th><th>具体任务</th></tr></thead><tbody>{notes.members.filter(m => m.name || m.studentId || m.responsibility).map((member, i) => <tr key={i}><td>{member.name}</td><td>{member.studentId}</td><td>{member.responsibility}</td></tr>)}</tbody></table></section>
      <footer><p>本报告中的开发、测试、成本和进度均为教学模拟。平台软件自身的测试结果不能当作被模拟项目的真实交付证据。</p><p>实验编号 {run} · Seed {project.seed} · {report?.scenario_version || '进行中'}</p></footer>
    </article>
  </div>
}
