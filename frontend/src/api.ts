export type Project = { id: string; name: string; description: string; sponsor_mode: string; llm_mode: string; step_mode: boolean; seed: number; status: string; phase: string }
export type Pending = { id: string; target_id: string; target_version: number; kind: string; status: string }
export type Delivery = { run_id: string; project_id: string; status: string; phase: string; error: string | null; pending_approvals: Pending[] }
export type Task = { id: string; title: string; duration_days: number; budget_cents: number; resource_id: string }
export type Plan = { version: number; tasks: Task[]; dependencies: { predecessor: string; successor: string; lag_days: number }[]; resources: { id: string; capacity: number; rate_cents_per_day: number }[] }
export type Metric = { status_day: number; baseline_version: number; pv_cents: number; ev_cents: number; ac_cents: number; bac_cents: number; spi: string | null; cpi: string | null; eac_cents: string | null }
export type Snapshot = { day: number; baseline_id?: string; tasks: Record<string, { accepted_day: number | null; attempts: number; rework_left: number; work_done: number; actual_cost_cents: number }> }
export type Simulation = { status: string; error: string | null; plan_status: string; current_plan: Plan; snapshot: Snapshot | null; metrics: Metric[]; ticks: { day: number; assignments: string[]; events: Record<string, unknown>[] }[] }
export type Baseline = { id: string; version: number; effective_day: number; previous_id: string | null; content_hash: string; content: { plan: Plan; schedule: { duration_days: number; critical_task_ids: string[]; tasks: Record<string, { es: number; ef: number; total_float: number }> } } }
export type Change = { id: string; artifact_id: string; reason: string; status: string; source_baseline_id: string; applied_baseline_id: string | null; impact: { delta_bac_cents: number; delta_duration_days: number; added_task_ids: string[]; execution_transition?: { source_day: number; source_snapshot_hash: string; pv_anchor: { pv_cents: number; finish_day: number; bac_cents: number }; remaining_forecast: Record<string, { start: number; finish: number }> } } }
export type Trace = { node: string; role: string; attempt: number; valid: boolean; error: string | null; elapsed_ms: number; provider: string; input_hash: string; output: { rationale?: string; payload?: Record<string, unknown> } }
export type Artifact = { id: string; kind: string; version: number; author: string; payload: Record<string, unknown> }
export type Report = { accepted: boolean; status: string; report: { title: string; simulation_days: number; seed: number; scenario_version: string; engine_version: string; final_metrics: Metric; management_lessons: string[]; performance_analysis?: { assessment: string; risks: string[] } | null; limitations: string[]; scope_acceptance: { task_id: string; title: string; accepted_day: number; acceptance_criteria: string[]; simulated_test_attempts: number }[] }; approval: Pending & { decision?: { reason: string; decision: string } | null } }
export type RunData = { delivery: Delivery; simulation: Simulation | null; baselines: Baseline[]; changes: Change[]; traces: Trace[]; artifacts: Artifact[]; report: Report | null }
export const terminal = (status: string) => ['completed', 'rejected', 'acceptance_rejected', 'failed'].includes(status)

export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { ...init, headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, typeof body.detail === 'string' ? body.detail : `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}
export async function optional<T>(path: string): Promise<T | null> { try { return await api<T>(path) } catch (e) { if (e instanceof ApiError && e.status === 404) return null; throw e } }
export const post = <T,>(path: string, body?: unknown, key?: string) => api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body), headers: key ? { 'Idempotency-Key': key } : undefined })
export const money = (cents: number | string | undefined) => cents === undefined ? '—' : new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 2 }).format(Number(cents) / 100)
export const ratio = (value?: string | null) => value == null ? '—' : Number(value).toFixed(2)
