import { useEffect, useRef, useState } from 'react'
import { api, money, post, ratio, terminal } from './api'
import type { Artifact, Baseline, Change, Metric, Pending, Plan, Project, Report, RunData, Trace } from './api'
import { useEvents, useRun } from './hooks'
import ExperimentReport from './ExperimentReport'

const roles = [
  ['sponsor', '发起人', 'SP', '需求与审批'], ['project_manager', '项目经理', 'PM', '协调与管理'],
  ['requirements_analyst', '需求分析师', 'RA', '范围与 WBS'], ['developer', '开发工程师', 'DE', '模拟开发与修复'],
  ['tester', '测试工程师', 'QA', '模拟测试与回归'], ['progress_cost_analyst', '绩效分析师', 'PC', '进度与成本'],
] as const
const labels: Record<string, string> = { completed: '已完成验收', waiting_step: '等待推进下一工作日', waiting_approval: '等待发起人审批', running: '协作进行中', ready: '准备中', failed: '执行中断', rejected: '提案被拒绝', acceptance_rejected: '最终验收未通过', waiting_change: '变更待审批', waiting_acceptance: '等待最终验收', initiating: '项目启动', awaiting_m3: '角色提案就绪', plan_approved: '计划已批准', approve: '批准', reject: '拒绝', applied: '已应用', proposed: '已提出', pending: '待审批' }
const names: Record<string, string> = { project_manager: '项目章程', plan: '计划与变更', closure_candidate: '最终验收', requirements_analyst: '需求规格与 WBS', planning_estimates: '资源估算', change_spec: '变更范围说明', sponsor: '需求简述', project_report: '结项报告' }
const defaultDescription = 'Library catalog management, reader management, borrowing, returns and search.'
const bookingDescription = 'Campus laboratory booking, room catalog, availability checks and booking history.'
type View = 'overview' | 'plan' | 'agents' | 'changes' | 'report'
const views: [View, string, string][] = [['overview', '实验总览', '◈'], ['plan', '范围与计划', '▥'], ['agents', '协作与轨迹', '◎'], ['changes', '变更与审批', '⇄'], ['report', '结项报告', '▤']]
const saveJson = (filename: string, value: unknown) => { const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }

export default function App() {
  const [run, setRun] = useState(() => new URLSearchParams(location.search).get('run') || localStorage.getItem('pm-run') || '')
  const [projects, setProjects] = useState<Project[]>([]), [project, setProject] = useState<Project | null>(null)
  const [view, setView] = useState<View>('overview'), [revision, setRevision] = useState(0), [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(''), [day, setDay] = useState<number | null>(null), [role, setRole] = useState('')
  const [allEvents, setAllEvents] = useState(false)
  const [playing, setPlaying] = useState(false), [replayPending, setReplayPending] = useState(false), [reportOpen, setReportOpen] = useState(false)
  const lastRequestedDay = useRef(-1)
  const dialog = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState('Library Management System'), [description, setDescription] = useState(defaultDescription)
  const [sponsor, setSponsor] = useState('llm'), [model, setModel] = useState('mock'), [seed, setSeed] = useState(42), [stepMode, setStepMode] = useState(true)
  const { data, error } = useRun(run, revision)
  const done = !!data && terminal(data.delivery.status)
  const { events, connected } = useEvents(run, done)

  async function refreshProjects() { const list = await api<Project[]>('/projects?limit=100'); setProjects(list); return list }
  useEffect(() => { void refreshProjects().catch(e => setActionError(String(e.message))) }, [])
  useEffect(() => { if (data) { const p = projects.find(p => p.id === data.delivery.project_id); if (p) setProject(p) } }, [data, projects])
  useEffect(() => { if (run) { localStorage.setItem('pm-run', run); const url = new URL(location.href); url.searchParams.set('run', run); history.replaceState(null, '', url) }; setDay(null); setPlaying(false); lastRequestedDay.current = -1 }, [run])

  async function start(quick = false) {
    if (busy) return
    setBusy(true); setActionError('')
    try {
      const created = await post<Project>('/projects', { name: quick ? 'Library Management System' : name, description: quick ? defaultDescription : description, sponsor_mode: quick ? 'llm' : sponsor, llm_mode: quick ? 'mock' : model, step_mode: quick ? false : stepMode, seed: quick ? 42 : seed })
      setProject(created); await refreshProjects()
      const delivery = await post<{ run_id: string }>(`/projects/${created.id}/delivery`, undefined, crypto.randomUUID())
      setRun(delivery.run_id); setReplayPending(quick); setView('overview'); setRevision(n => n + 1); dialog.current?.close()
    } catch (e) { setActionError(e instanceof Error ? e.message : '启动失败；可从项目列表恢复') } finally { setBusy(false) }
  }
  async function openProject(id: string) {
    const selected = projects.find(p => p.id === id); if (!selected) return
    setProject(selected); setActionError(''); setPlaying(false); setReplayPending(false)
    try { const rows = await api<{ id: string; delivery: boolean }[]>(`/projects/${id}/runs`); const delivery = rows.find(row => row.delivery); if (delivery) { setRun(delivery.id); setRevision(n => n + 1) } else { setRun(''); setActionError('该项目尚无自动交付记录，请新建实验或使用 API 启动。') } } catch (e) { setActionError((e as Error).message) }
  }
  async function approve(a: Pending, decision: string, reason: string) {
    setBusy(true); setActionError('')
    try {
      const path = a.kind === 'project_manager' ? `/runs/${run}/approvals/${a.id}` : a.kind === 'plan' ? `/runs/${run}/plan-approvals/${a.id}/decision` : `/runs/${run}/simulation/acceptance`
      await post(path, { target_id: a.target_id, target_version: a.target_version, decision, reason: reason.trim() || (decision === 'approve' ? '发起人已审阅并批准此版本。' : '发起人审阅后拒绝此版本，需调整。') })
      await post(`/runs/${run}/delivery/resume`); setRevision(n => n + 1); await refreshProjects()
    } catch (e) { setActionError((e as Error).message) } finally { setBusy(false) }
  }
  async function resume() { setBusy(true); try { await post(`/runs/${run}/delivery/resume`); setRevision(n => n + 1); setActionError('') } catch (e) { setActionError((e as Error).message) } finally { setBusy(false) } }

  async function advanceDay() {
    if (busy || !data || data.delivery.status !== 'waiting_step') return
    const current = data.simulation?.snapshot?.day ?? 0
    if (lastRequestedDay.current === current) return
    lastRequestedDay.current = current
    setBusy(true)
    try { await post(`/runs/${run}/delivery/resume`); setActionError('') }
    catch (e) { lastRequestedDay.current = -1; setPlaying(false); setActionError((e as Error).message) }
    finally { setBusy(false) }
  }

  const simulation = data?.simulation, latestDay = simulation?.snapshot?.day || 0, currentDay = day ?? latestDay
  const metric = simulation?.metrics.find(m => m.status_day === currentDay)
  const baseline = data?.baselines.find(b => b.version === metric?.baseline_version) || data?.baselines.at(-1)
  const plan = baseline?.content.plan || simulation?.current_plan
  const status = data?.delivery.status || (run ? 'ready' : '')
  const pending = data?.delivery.pending_approvals.filter(a => a.status === 'pending') || []
  const group = currentDay === 0 && simulation ? 1 : currentDay < latestDay ? 3 :
    ['completed', 'acceptance_rejected'].includes(status) || simulation?.status === 'waiting_acceptance' ? 4 :
    simulation ? 3 : (data?.artifacts.some(a => a.kind === 'requirements_analyst') ? 1 : 0)
  const acceptedCount = plan?.tasks.filter(t => { const accepted = simulation?.snapshot?.tasks[t.id]?.accepted_day; return accepted != null && accepted <= currentDay }).length || 0
  const analysis = data?.traces.find(t => t.valid && t.node === `execution:${currentDay}:progress_cost_analyst:monitor`)?.output.payload

  useEffect(() => {
    if (replayPending && done && latestDay > 0) { setDay(0); setPlaying(true); setReplayPending(false) }
  }, [replayPending, done, latestDay])
  useEffect(() => {
    if (!playing || !run) return
    if (day !== null && day < latestDay) {
      const timer = setTimeout(() => setDay(value => Math.min((value ?? 0) + 1, latestDay)), 1300)
      return () => clearTimeout(timer)
    }
    if (status === 'waiting_step' && lastRequestedDay.current !== latestDay) {
      const timer = setTimeout(() => void advanceDay(), 1300)
      return () => clearTimeout(timer)
    }
    if (done && currentDay >= latestDay) setPlaying(false)
  }, [playing, run, day, latestDay, status, done, currentDay])

  if (reportOpen && data && project) return <ExperimentReport data={data} project={project} run={run} onClose={() => setReportOpen(false)}/>

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="项目协作实验室首页"><span className="brand-mark">⌘</span><span>项目协作实验室<small>PROJECT COLLAB LAB</small></span></a>
      <div className="sidebar-label">实验工作台</div>
      <nav aria-label="主导航">{views.map(([id, title, icon]) => <button key={id} className={view === id ? 'nav-item active' : 'nav-item'} onClick={() => setView(id)}><span>{icon}</span>{title}{id === 'changes' && pending.length > 0 && <i>{pending.length}</i>}</button>)}</nav>
      <div className="sidebar-project"><div className="sidebar-label">当前项目</div><select aria-label="选择项目" value={project?.id || ''} onChange={e => void openProject(e.target.value)}><option value="">选择实验项目</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><p>{project?.description || '创建一次实验，观察六个角色如何协作完成软件项目。'}</p></div>
      <div className="sidebar-bottom"><span className="badge outline">SIMULATION ONLY</span><p>模拟开发 · 模拟测试<br/>确定性计算 · 可恢复工作流</p><small>LangGraph / FastAPI / React</small></div>
    </aside>
    <main>
      <header className="topbar"><span>软件项目管理实验 <b>/</b> {views.find(v => v[0] === view)?.[1]}</span><div><span className="badge simulation">模拟结果</span><button className="button dark" onClick={() => dialog.current?.showModal()}>＋ 新建实验</button></div></header>
      <div className="workspace">
        <div className="page-heading"><div><div className="eyebrow">MULTI-AGENT PROJECT MANAGEMENT</div><h1>{project?.name || '让协作过程，看得见。'}</h1><p>{run ? `${project?.llm_mode === 'real' ? '真实模型决策' : 'Mock 模型决策'} · ${project?.sponsor_mode === 'human' ? '人工发起人' : '模拟发起人'} · Seed ${project?.seed ?? '—'}` : '从一份需求出发，观察计划、执行、变更与验收的完整过程。'}</p></div>{run && <div className="heading-actions"><span className={`status ${status === 'completed' ? 'success' : status === 'failed' ? 'danger' : ''}`} role="status">● {labels[status] || status}</span><button className="button light" onClick={() => setRevision(n => n + 1)}>刷新</button></div>}</div>
        {(actionError || error) && <div className="alert" role="alert">{actionError || error}{status === 'failed' && <button onClick={() => void resume()} disabled={busy}>恢复工作流</button>}</div>}
        {!run ? <section className="hero panel"><div><span className="badge outline">内置教学项目 / LMS</span><h2>一次项目，六种视角。</h2><p>图书管理系统示例包含需求分解、资源约束、缺陷返工，以及一次正式需求变更。无需 API Key，即可启动可复现的协作实验。</p><button className="button dark large" disabled={busy} onClick={() => void start(true)}>{busy ? '正在创建实验…' : '运行 Mock 示例 →'}</button><div className="hero-foot">五大过程组 <span>·</span> 六个协作角色 <span>·</span> 全程可追踪</div></div><div className="collab-visual" aria-hidden="true"><div className="orbit"/><div className="hub">共享项目状态<small>CONTROLLED WORKFLOW</small></div>{roles.map((r, i) => <div className={`orbit-role orbit-${i}`} key={r[0]}><strong>{r[2]}</strong><span>{r[1]}</span></div>)}</div></section> : <>
          <section className="process-strip" aria-label="五大过程组">{['启动', '规划', '执行', '监控与控制', '收尾'].map((name, i) => <div key={name} className={i <= group ? 'reached' : ''}><span>{String(i + 1).padStart(2, '0')}</span><b>{name}</b><small>{i < group || status === 'completed' ? '已推进' : i === group ? '当前阶段' : '待推进'}</small></div>)}</section>
          {pending.length > 0 && <section className="approval-section"><div className="section-heading"><h2>需要你的管理决策</h2><span>审批绑定具体产物与版本</span></div>{pending.map(a => <ApprovalCard key={a.id} approval={a} artifact={data?.artifacts.find(x => x.id === a.target_id)} changes={data?.changes || []} busy={busy} onDecide={(d, reason) => void approve(a, d, reason)} />)}</section>}
          {(view === 'overview' || view === 'plan') && <><div className="day-control"><span><b>第 {currentDay} 个模拟工作日</b> / {latestDay}<small>{day === null ? '当前进度' : '历史回放'}</small></span><div className="day-actions"><button className="button light" aria-label="上一工作日" title="上一工作日" disabled={currentDay === 0} onClick={() => { setPlaying(false); setDay(currentDay - 1) }}>←</button><button className="button light" aria-label={playing ? '暂停播放' : '播放模拟'} title={playing ? '暂停播放' : '播放模拟'} onClick={() => { if (done && currentDay >= latestDay) setDay(0); else if (day === null) setDay(currentDay); setPlaying(!playing) }}>{playing ? 'Ⅱ' : '▶'}</button><button className="button light" aria-label="下一工作日" title="下一工作日" disabled={busy || (currentDay >= latestDay && status !== 'waiting_step')} onClick={() => { setPlaying(false); if (currentDay < latestDay) setDay(currentDay + 1); else void advanceDay() }}>→</button></div><input aria-label="查看模拟日" type="range" min="0" max={Math.max(latestDay, 1)} value={currentDay} disabled={!latestDay} onChange={e => { setPlaying(false); setDay(Number(e.target.value)) }}/><button className="text-button" onClick={() => { setPlaying(false); setDay(null) }}>回到最新</button></div><DayActivity day={currentDay} data={data}/></>}
          {view === 'overview' && <>
            <MetricCards metric={metric}/>
            <section className="role-grid">{roles.map(r => <button className="role-card" key={r[0]} onClick={() => { setRole(r[0]); setView('agents') }}><span className={`avatar role-${r[0]}`}>{r[2]}</span><strong>{r[1]}</strong><small>{r[3]}</small><b>{data?.traces.filter(t => t.role === r[0]).length || 0}<em> 次决策</em></b></button>)}</section>
            <div className="overview-grid"><section className="panel"><div className="section-heading"><div><div className="eyebrow">EARNED VALUE MANAGEMENT</div><h2>价值与成本走势</h2></div><span>单位：人民币</span></div><CostChart metrics={simulation?.metrics || []} day={currentDay}/></section><section className="panel summary-panel"><div className="eyebrow">PROJECT SNAPSHOT</div><h2>当前管理快照</h2><dl><dt>当前基准</dt><dd>{baseline ? `V${baseline.version}` : '尚未批准'}</dd><dt>范围验收进度</dt><dd>{acceptedCount} / {plan?.tasks.length || 0} 项</dd><dt>已获批变更</dt><dd>{data?.changes.filter(c => c.status === 'applied' && data.baselines.some(b => b.id === c.applied_baseline_id && b.version <= (baseline?.version || 0))).length || 0} 次</dd><dt>CPM 计划工期</dt><dd>{baseline?.content.schedule.duration_days ?? '—'} 个工作日</dd><dt>当前模拟日</dt><dd>{currentDay} 日</dd><dt>事件记录</dt><dd>{events.length} 条</dd></dl><progress className="scope-progress" aria-label="模拟任务验收进度" value={acceptedCount} max={Math.max(plan?.tasks.length || 0, 1)}/><p className="footnote">CPM 不考虑资源等待。模拟工期还受到资源容量、缺陷与返工影响。</p><button className="button light" onClick={() => setView('plan')}>查看 WBS 与甘特图 ↗</button></section></div>
          </>}
          {view === 'overview' && analysis && <section className="panel performance-panel"><div className="section-heading"><h2>绩效分析师 · 关键路径与偏差解读</h2><span>基于当前模拟日的确定性计算</span></div><p>{String(analysis.assessment || '')}</p><ul>{Array.isArray(analysis.risks) && analysis.risks.map((risk, i) => <li key={i}>{String(risk)}</li>)}</ul></section>}
          {view === 'plan' && <><Gantt plan={plan} baseline={baseline} run={run}/><Scope artifacts={data?.artifacts || []}/></>}
          {view === 'agents' && <><div className="role-filters"><button className={!role ? 'selected' : ''} onClick={() => setRole('')}>全部角色</button>{roles.map(r => <button key={r[0]} className={role === r[0] ? 'selected' : ''} onClick={() => setRole(r[0])}>{r[1]}</button>)}</div><section className="panel"><div className="section-heading"><h2>结构化决策记录</h2><span>{data?.traces.length || 0} 次执行尝试</span></div><Traces traces={(data?.traces || []).filter(t => !role || t.role === role)}/></section></>}
          {view === 'changes' && <><Changes changes={data?.changes || []}/><section className="panel"><div className="section-heading"><h2>批准基准历史</h2><span>历史版本只读</span></div>{data?.baselines.length ? data.baselines.map(b => <div className="baseline-row" key={b.id}><span className="version">V{b.version}</span><div><strong>{b.version === 1 ? '初始计划基准' : '正式变更后的新基准'}</strong><small>第 {b.effective_day} 日生效 · {b.content.plan.tasks.length} 项任务 · BAC {money(b.content.plan.tasks.reduce((s, t) => s + t.budget_cents, 0))}</small></div><code title={b.content_hash}>{b.content_hash.slice(0, 12)}</code></div>) : <Empty text="尚无获批基准。"/>}</section></>}
          {view === 'report' && <><div className="report-export"><button className="button dark" disabled={!data?.report} onClick={() => setReportOpen(true)}>生成实验报告 ↗</button></div><ReportView report={data?.report || null}/></>}
          <section className="panel events-panel"><div className="section-heading"><h2>工作流事件</h2><div className="heading-actions"><span className="stream-status"><i className={connected ? 'online' : ''}/>{done ? '持久记录' : connected ? '实时连接' : '正在重连'}</span><button className="text-button" onClick={() => setAllEvents(!allEvents)}>{allEvents ? '仅看最近事件' : `查看全部 ${events.length} 条`}</button></div></div><div className="events-list">{events.length ? (allEvents ? events : events.slice(-12)).slice().reverse().map(e => <div key={e.id}><code>#{e.id.toString().padStart(3, '0')}</code><b>{eventLabel(e.kind)}</b><span>{eventSummary(e.data)}</span></div>) : <Empty text={data ? '等待工作流事件…' : '正在连接后端并读取项目…'}/>}</div></section>
        </>}
        <footer>软件项目管理教学实验 <span>所有开发成果与测试结论均为模拟结果</span></footer>
      </div>
    </main>
    <dialog ref={dialog}><form onSubmit={e => { e.preventDefault(); void start() }}><div className="section-heading"><div><div className="eyebrow">NEW EXPERIMENT</div><h2>创建项目管理实验</h2></div><button type="button" className="close" aria-label="关闭" onClick={() => dialog.current?.close()}>×</button></div><label>Mock 场景<select aria-label="Mock 场景" onChange={e => { if (e.target.value === 'library') { setName('Library Management System'); setDescription(defaultDescription) } else if (e.target.value === 'booking') { setName('Campus Lab Booking'); setDescription(bookingDescription) } else { setName('Custom Project'); setDescription('Describe the agreed requirements here.') } }}><option value="library">图书管理系统</option><option value="booking">实验室预约系统</option><option value="custom">其他需求（通用演练）</option></select></label><label>项目名称<input required maxLength={200} value={name} onChange={e => setName(e.target.value)}/></label><label>初始需求<textarea required rows={4} value={description} onChange={e => setDescription(e.target.value)}/></label><div className="form-grid"><label>发起人模式<select value={sponsor} onChange={e => setSponsor(e.target.value)}><option value="llm">模拟发起人自动审批</option><option value="human">Human · 人工审批</option></select></label><label>角色决策模式<select value={model} onChange={e => setModel(e.target.value)}><option value="mock">Mock · 无需密钥</option><option value="real">真实模型 · 使用服务器配置</option></select></label></div><label className="check-setting"><input type="checkbox" checked={stepMode} onChange={e => setStepMode(e.target.checked)}/><span>逐日演示：每个模拟工作日后暂停</span></label><label>随机种子<input type="number" min={0} max={2147483647} required value={seed} onChange={e => setSeed(Number(e.target.value))}/></label><p className="footnote">Mock 对图书管理和实验室预约使用预设任务；其他需求采用单任务通用演练。真实模型模式会调用服务器上配置的 API。</p>{actionError && <p className="alert" role="alert">{actionError}</p>}<button className="button dark large" disabled={busy}>{busy ? '正在启动…' : '启动模拟实验 →'}</button></form></dialog>
  </div>
}

function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
function DayActivity({ day, data }: { day: number; data: RunData | null }) {
  const tick = data?.simulation?.ticks.find(t => t.day === day)
  const traces = (data?.traces || []).filter(t => day === 0 ? !t.node.startsWith('execution:') : t.node.startsWith(`execution:${day}:`))
  const tasks = data?.baselines.at(-1)?.content.plan.tasks || []
  const taskName = (id: string) => tasks.find(t => t.id === id)?.title || id
  return <section className="day-activity" aria-label="当日模拟活动"><div className="section-heading"><h2>第 {day} 日活动</h2><span>{day === 0 ? '启动与计划' : `${tick?.assignments.length || 0} 项分配 · ${tick?.events.length || 0} 条执行事件 · ${traces.length} 次角色决策`}</span></div>{day === 0 ? <p>项目章程、需求和计划已形成；从下一工作日开始模拟执行。</p> : <><div className="activity-lines">{tick?.assignments.map(id => <span key={id}>执行任务：{taskName(id)}</span>)}{tick?.events.map((event, i) => <span key={i}>{eventLabel(String(event.kind))}{event.task_id ? ` · ${taskName(String(event.task_id))}` : event.description ? ` · ${String(event.description)}` : ''}</span>)}{!tick?.assignments.length && !tick?.events.length && <span>当日无任务执行，等待前置任务或资源。</span>}</div><div className="activity-roles">{traces.map((trace, i) => <span key={`${trace.node}:${i}`}>{roles.find(r => r[0] === trace.role)?.[1] || trace.role}：{trace.node.split(':').at(-1)}</span>)}</div></>}</section>
}
function MetricCards({ metric }: { metric?: Metric }) { return <section className="metric-grid" aria-label="挣值管理指标">{[['计划价值 PV', metric ? money(metric.pv_cents) : '—', '批准计划的累计价值'], ['挣值 EV', metric ? money(metric.ev_cents) : '—', '通过模拟验收的工作价值'], ['实际成本 AC', metric ? money(metric.ac_cents) : '—', '模拟消耗的累计成本'], ['进度绩效 SPI', ratio(metric?.spi), 'EV / PV'], ['成本绩效 CPI', ratio(metric?.cpi), 'EV / AC']].map(([title, value, hint]) => <article key={title}><span>{title}</span><strong>{value}</strong><small>{hint}</small></article>)}</section> }

function CostChart({ metrics, day }: { metrics: Metric[]; day: number }) {
  if (!metrics.length) return <Empty text="推进模拟后将在这里显示 PV / EV / AC。"/>
  const width = 720, height = 260, left = 58, top = 22, bottom = 35
  const max = Math.max(1, ...metrics.flatMap(m => [m.pv_cents, m.ev_cents, m.ac_cents])), days = Math.max(1, ...metrics.map(m => m.status_day))
  const x = (d: number) => left + d / days * (width - left - 20), y = (v: number) => height - bottom - v / max * (height - top - bottom)
  const series = [['pv_cents', 'PV 计划价值', '#9eacb4'], ['ev_cents', 'EV 挣值', '#2d775c'], ['ac_cents', 'AC 实际成本', '#b98547']] as const
  return <><div className="chart-legend">{series.map(([, name, color]) => <span key={name}><i style={{ background: color }}/>{name}</span>)}</div><svg className="cost-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="计划价值、挣值与实际成本按模拟日的变化">{[0, .25, .5, .75, 1].map(f => <g key={f}><line x1={left} x2={width - 20} y1={y(max * f)} y2={y(max * f)} stroke="#e9ece8"/><text x={left - 9} y={y(max * f) + 4} textAnchor="end">{(max * f / 100).toFixed(0)}</text></g>)}{metrics.map(m => <text key={m.status_day} x={x(m.status_day)} y={height - 11} textAnchor="middle">{m.status_day}</text>)}<line x1={x(day)} x2={x(day)} y1={top} y2={height - bottom} stroke="#d1d7cd" strokeDasharray="4 4"/>{series.map(([key, label, color]) => <g key={key}><polyline points={metrics.map(m => `${x(m.status_day)},${y(m[key])}`).join(' ')} fill="none" stroke={color} strokeWidth="2.8"/>{metrics.map(m => <circle key={m.status_day} cx={x(m.status_day)} cy={y(m[key])} r={m.status_day === day ? 4 : 2.5} fill={color}><title>{label} · 第 {m.status_day} 日：{money(m[key])}</title></circle>)}</g>)}</svg><p className="chart-caption">横轴：模拟工作日 · 指标按各日生效基准保留，变更前历史不回写</p></>
}

function Gantt({ plan, baseline, run }: { plan?: Plan; baseline?: Baseline; run: string }) {
  if (!plan || !baseline) return <section className="panel"><h2>WBS 与计划甘特图</h2><Empty text="计划批准后显示任务、依赖与关键路径。"/></section>
  const schedule = baseline.content.schedule, total = Math.max(schedule.duration_days, 1)
  return <section className="panel"><div className="section-heading"><div><div className="eyebrow">WORK BREAKDOWN STRUCTURE</div><h2>WBS 与计划甘特图 <span className="badge outline">V{plan.version}</span></h2></div><div className="gantt-tools"><span><i className="legend-critical"/>关键任务 · CPM {total} 日</span><a className="button light" href={`/api/v1/runs/${run}/export?baseline_version=${baseline.version}`}>导出 Microsoft Project XML ↓</a></div></div><div className="table-scroll"><table className="gantt-table"><thead><tr><th>WBS / 任务</th><th>工期</th><th>预算</th><th>前置任务</th><th className="gantt-axis">{Array.from({ length: total + 1 }, (_, i) => <span key={i} style={{ left: `${i / total * 100}%` }}>{i}</span>)}</th></tr></thead><tbody>{plan.tasks.map(t => { const row = schedule.tasks[t.id], critical = schedule.critical_task_ids.includes(t.id); return <tr key={t.id}><td><code>{t.id}</code><strong>{t.title}</strong>{critical && <small className="critical-text">关键路径</small>}</td><td>{t.duration_days} 日</td><td>{money(t.budget_cents)}</td><td>{plan.dependencies.filter(d => d.successor === t.id).map(d => `${d.predecessor}${d.lag_days ? ` +${d.lag_days}d` : ''}`).join(', ') || '—'}</td><td className="gantt-track"><div className={critical ? 'gantt-bar critical' : 'gantt-bar'} style={{ left: `${row.es / total * 100}%`, width: `${t.duration_days / total * 100}%` }} title={`ES ${row.es} · EF ${row.ef} · 浮时 ${row.total_float}`}>{t.duration_days}d</div></td></tr> })}</tbody></table></div><p className="footnote">区间 [开始, 完成)，单位为工作日。此图展示批准计划；实际模拟还包含资源等待和返工。</p></section>
}

function Scope({ artifacts }: { artifacts: Artifact[] }) {
  const charter = artifacts.find(a => a.kind === 'project_manager'), srs = artifacts.find(a => a.kind === 'requirements_analyst')
  const strings = (a: Artifact | undefined, field: string) => Array.isArray(a?.payload[field]) ? (a?.payload[field] as string[]) : []
  const tasks = (srs?.payload.tasks || []) as { id: string; title: string; acceptance_criteria: string[] }[]
  return <div className="scope-grid"><section className="panel"><div className="eyebrow">PROJECT CHARTER</div><h2>项目章程</h2>{strings(charter, 'objectives').map((s, i) => <p key={i}>{s}</p>)}<h3>成功标准</h3><ul>{strings(charter, 'success_criteria').map((s, i) => <li key={i}>{s}</li>)}</ul><h3>项目约束</h3><ul>{strings(charter, 'constraints').map((s, i) => <li key={i}>{s}</li>)}</ul><h3>干系人</h3><p>{strings(charter, 'stakeholders').join(' · ')}</p></section><section className="panel"><div className="eyebrow">SRS / ACCEPTANCE</div><h2>范围与验收标准</h2>{tasks.map(t => <details key={t.id}><summary>{t.id} · {t.title}</summary><ul>{t.acceptance_criteria.map((c, i) => <li key={i}>{c}</li>)}</ul></details>)}<h3>范围之外</h3><p>{strings(srs, 'out_scope').join(' / ') || '待需求分析完成'}</p></section></div>
}

function Traces({ traces }: { traces: Trace[] }) { return traces.length ? <div className="trace-list">{traces.map(t => { const r = roles.find(r => r[0] === t.role); return <details key={`${t.node}:${t.attempt}`} className="trace"><summary><span className={`avatar role-${t.role}`}>{r?.[2] || 'AG'}</span><div><strong>{r?.[1] || t.role}</strong><small>{t.node}</small></div><span className={`badge ${t.valid ? 'ok' : 'bad'}`}>{t.valid ? '校验通过' : '校验失败'}</span><span className="trace-time">{t.elapsed_ms} ms</span></summary><p>{t.output.rationale || t.error}</p><small>Provider {t.provider} · 第 {t.attempt} 次尝试 · 输入摘要 {t.input_hash.slice(0, 12)}</small><pre>{JSON.stringify(t.output.payload || {}, null, 2)}</pre></details> })}</div> : <Empty text="角色决策将在执行后出现。"/> }

function Changes({ changes }: { changes: Change[] }) { return <section className="panel"><div className="section-heading"><div><div className="eyebrow">CHANGE CONTROL</div><h2>正式变更记录</h2></div><span>提案 → 影响分析 → 审批 → 基准更新</span></div>{changes.length ? changes.map((c, i) => <article className="change-card" key={c.id}><div className="section-heading"><h3>CR-{String(i + 1).padStart(2, '0')} · {c.reason}</h3><span className={`badge ${c.status === 'applied' ? 'ok' : ''}`}>{labels[c.status] || c.status}</span></div><div className="change-deltas"><span>预算影响 <strong>+{money(c.impact.delta_bac_cents)}</strong></span><span>CPM 工期影响 <strong>+{c.impact.delta_duration_days} 日</strong></span><span>新增任务 <strong>{c.impact.added_task_ids.length} 项</strong></span></div><small>{c.applied_baseline_id ? '已通过正式审批并关联新基准，旧基准保留。' : '尚未应用新基准；原批准计划继续有效。'}</small><RemainingPlan change={c}/></article>) : <Empty text="模拟到达场景变更点后，将显示正式影响分析与审批结果。"/>}</section> }

function ApprovalCard({ approval: a, artifact, changes, busy, onDecide }: { approval: Pending; artifact?: Artifact; changes: Change[]; busy: boolean; onDecide: (decision: string, reason: string) => void }) {
  const [reason, setReason] = useState(''), change = changes.find(c => c.artifact_id === a.target_id)
  return <article className="approval-card"><div><span className="badge amber">待人工审批</span><h3>{names[a.kind] || a.kind} · 产物版本 {a.target_version}</h3><p>请审阅当前对象。此决策只对该产物与版本生效。</p>{change && <p>预算影响 {money(change.impact.delta_bac_cents)} · 工期影响 {change.impact.delta_duration_days} 日</p>}<details><summary>审阅产物内容</summary><pre>{JSON.stringify(artifact?.payload || {}, null, 2)}</pre></details>{change && <RemainingPlan change={change}/>}</div><div className="approval-actions"><label>审批意见<textarea aria-label="审批意见" rows={2} placeholder="说明批准或拒绝的理由" value={reason} onChange={e => setReason(e.target.value)}/></label><div><button className="button light" disabled={busy} onClick={() => onDecide('reject', reason)}>拒绝</button><button className="button dark" disabled={busy} onClick={() => onDecide('approve', reason)}>批准并继续</button></div></div></article>
}

function ReportView({ report }: { report: Report | null }) {
  if (!report) return <section className="panel"><div className="eyebrow">CLOSURE / LESSONS LEARNED</div><h2>结项与管理报告</h2><Empty text="全部模拟范围完成后，PM 将生成候选报告并请求发起人验收。"/></section>
  const r = report.report
  return <section className="panel report"><div className="section-heading"><div><div className="eyebrow">PROJECT CLOSURE REPORT</div><h2>{r.title}</h2></div><button className="button light" onClick={() => saveJson('simulation-report.json', report)}>下载 JSON 报告 ↓</button></div><div className={report.accepted ? 'report-result accepted' : 'report-result'}><b>{report.accepted ? '✓ 发起人已完成最终验收' : report.status === 'acceptance_rejected' ? '最终验收未通过' : '候选报告 · 等待发起人最终验收'}</b><span>模拟 {r.simulation_days} 日 · Seed {r.seed} · {r.scenario_version}</span></div><MetricCards metric={r.final_metrics}/><h3>范围验收与模拟测试</h3><div className="table-scroll"><table><thead><tr><th>任务</th><th>验收标准</th><th>模拟验收日</th><th>模拟测试次数</th></tr></thead><tbody>{r.scope_acceptance.map(t => <tr key={t.task_id}><td><b>{t.title}</b></td><td>{t.acceptance_criteria.join('；')}</td><td>第 {t.accepted_day} 日</td><td>{t.simulated_test_attempts}</td></tr>)}</tbody></table></div><h3>项目管理经验</h3>{r.performance_analysis && <div className="performance-panel"><p>{r.performance_analysis.assessment}</p><ul>{r.performance_analysis.risks.map((risk, i) => <li key={i}>{risk}</li>)}</ul></div>}<ul>{r.management_lessons.map((s, i) => <li key={i}>{s}</li>)}</ul>{report.approval.decision && <p><b>发起人意见：</b>{report.approval.decision.reason}</p>}<div className="simulation-note"><b>模拟结果说明</b>{r.limitations.map((s, i) => <p key={i}>{s}</p>)}<p>报告中的开发、缺陷和测试仅为项目管理教学模拟，不代表真实代码已实现或运行。</p></div></section>
}

function eventLabel(kind: string) { const map: Record<string, string> = { simulated_development: '模拟开发', simulated_repair: '模拟缺陷修复', simulated_test_passed: '模拟测试通过', simulated_test_failed: '模拟测试发现缺陷', simulation_metrics: '绩效指标已更新', change_requested: '场景触发需求变更', prepare_simulation_change: 'PM 提交正式变更', review_simulation_change: '变更审批后继续执行', archive_closure: '最终验收已归档', prepare_closure: 'PM 请求结项验收', delivery_build_plan: 'WBS 与估算生成计划' }; return map[kind] || roles.find(r => r[0] === kind)?.[1] || (kind.startsWith('apply_plan_approval:') ? '计划审批结果已提交' : '工作流状态更新') }
function eventSummary(data: Record<string, unknown>) { if ('pv_cents' in data) return `第 ${data.status_day} 日 · PV ${money(Number(data.pv_cents))} · EV ${money(Number(data.ev_cents))} · AC ${money(Number(data.ac_cents))}`; return [data.day ? `第 ${data.day} 日` : '', data.task_id ? `任务 ${data.task_id}` : '', data.result ? labels[String(data.result)] : ''].filter(Boolean).join(' · ') }


function RemainingPlan({ change }: { change: Change }) {
  const basis = change.impact.execution_transition
  if (!basis) return null
  return <details className="remaining-plan"><summary>剩余计划与 PV 分配依据</summary><p>以第 {basis.source_day} 日累计 PV {money(basis.pv_anchor.pv_cents)} 为锚点，将剩余预算均匀分配至第 {basis.pv_anchor.finish_day} 日。此预测包含已发生进度，未考虑未来资源等待或未知返工。</p><div className="table-scroll"><table><thead><tr><th>任务</th><th>预测开始日</th><th>预测完成日</th></tr></thead><tbody>{Object.entries(basis.remaining_forecast).map(([id, dates]) => <tr key={id}><td>{id}</td><td>{dates.start}</td><td>{dates.finish}</td></tr>)}</tbody></table></div><p>源快照摘要：<code>{basis.source_snapshot_hash.slice(0, 16)}</code> · 该依据经审批通过后写入不可变基准。</p></details>
}
