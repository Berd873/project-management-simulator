import json
import time

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..agents.contracts import ApprovalDecision
from ..models import AgentExecution, Approval, Event, Project, Run, SimulationRun


def run_router(runtime):
    router = APIRouter(prefix='/api/v1')

    def load(s, run_id):
        run = s.get(Run, run_id)
        if not run:
            raise HTTPException(404, 'Run not found')
        return run

    def execute(run_id, decision=None):
        with runtime.lock:
            runtime.drive(run_id, decision)

    @router.post('/projects/{project_id}/runs', status_code=202)
    def start(project_id: str, tasks: BackgroundTasks, idempotency_key: str = Header(min_length=1, max_length=100)):
        with runtime.lock, runtime.sessions.begin() as s:
            if not s.get(Project, project_id):
                raise HTTPException(404, 'Project not found')
            existing = s.scalar(select(Run).where(Run.project_id == project_id, Run.request_key == idempotency_key))
            if existing:
                return {'id': existing.id, 'status': existing.status}
            active = s.scalar(select(Run).where(Run.project_id == project_id, Run.status.not_in(['rejected'])))
            if active:
                raise HTTPException(409, 'Project already has a run; resume it instead')
            run = Run(project_id=project_id, request_key=idempotency_key)
            s.add(run)
            s.flush()
            result = {'id': run.id, 'status': run.status}
        tasks.add_task(execute, result['id'])
        return result

    @router.get('/runs/{run_id}')
    def status(run_id: str):
        with runtime.sessions() as s:
            run = load(s, run_id)
            approvals = s.scalars(select(Approval).where(Approval.run_id == run_id)).all()
            return {'id': run.id, 'project_id': run.project_id, 'status': run.status, 'error': run.error,
                    'execution_mode': 'simulation', 'workflow_version': 'm2-v1',
                    'approvals': [{'id': a.id, 'target_id': a.target_id, 'target_version': a.target_version, 'status': a.status} for a in approvals]}

    @router.post('/runs/{run_id}/resume', status_code=202)
    def resume(run_id: str, tasks: BackgroundTasks):
        with runtime.lock, runtime.sessions.begin() as s:
            run = load(s, run_id)
            if run.status not in ['failed', 'ready']:
                raise HTTPException(409, 'Only failed or interrupted execution can retry; approvals use approval endpoint')
            run.status = 'ready'
        tasks.add_task(execute, run_id)
        return {'id': run_id, 'status': 'ready'}

    @router.post('/runs/{run_id}/approvals/{approval_id}', status_code=202)
    def approve(run_id: str, approval_id: str, decision: ApprovalDecision, tasks: BackgroundTasks):
        with runtime.lock, runtime.sessions() as s:
            run = load(s, run_id)
            approval = s.get(Approval, approval_id)
            if not approval or approval.run_id != run_id:
                raise HTTPException(404, 'Approval not found')
            if approval.target_id != decision.target_id or approval.target_version != decision.target_version:
                raise HTTPException(409, 'Stale approval target')
            if approval.decision:
                if approval.decision != decision.model_dump():
                    raise HTTPException(409, 'Approval already decided differently')
                return {'id': run_id, 'status': run.status}
            if run.status != 'waiting_approval':
                raise HTTPException(409, 'Run is not awaiting approval')
            # Persist intent before returning 202; graph commits decision and receipt later.
            approval.decision = decision.model_dump()
            run.status = 'ready'
            s.commit()
        tasks.add_task(execute, run_id, decision.model_dump())
        return {'id': run_id, 'status': 'ready'}

    @router.get('/runs/{run_id}/traces')
    def traces(run_id: str):
        with runtime.sessions() as s:
            load(s, run_id)
            return [{'node': t.node, 'role': t.role, 'attempt': t.attempt, 'provider': t.provider,
                     'input_hash': t.input_hash, 'output': t.output, 'valid': t.valid, 'error': t.error,
                     'elapsed_ms': t.elapsed_ms, 'prompt_version': t.prompt_version} for t in s.scalars(
                         select(AgentExecution).where(AgentExecution.run_id == run_id).order_by(AgentExecution.node, AgentExecution.attempt))]

    @router.get('/runs/{run_id}/events')
    def events(run_id: str, last_event_id: int = Header(0, ge=0), follow: bool = Query(True)):
        with runtime.sessions() as s:
            load(s, run_id)

        def stream():
            cursor = last_event_id
            while True:
                with runtime.sessions() as s:
                    rows = s.scalars(select(Event).where(Event.run_id == run_id, Event.sequence > cursor).order_by(Event.sequence)).all()
                    terminal = s.get(Run, run_id).status in ['awaiting_m3', 'rejected', 'failed', 'waiting_approval']
                    simulation = s.get(SimulationRun, run_id)
                    if simulation:
                        terminal = simulation.status in ['awaiting_m4','failed','waiting_change','waiting_acceptance','completed','acceptance_rejected']
                    batch = [(e.sequence, e.kind, e.payload) for e in rows]
                for seq, kind, payload in batch:
                    yield f'id: {seq}\nevent: {kind}\ndata: {json.dumps(payload)}\n\n'
                    cursor = seq
                if terminal or not follow:
                    break
                yield ': heartbeat\n\n'
                time.sleep(0.5)
        return StreamingResponse(stream(), media_type='text/event-stream')

    return router
