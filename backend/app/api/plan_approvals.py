from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ..agents.contracts import ApprovalDecision
from ..domain import Role
from ..models import Approval,Artifact,Baseline,ChangeRequest,NodeReceipt,Run,SimulationTick
from ..services.baselines import BaselineConflict,propose_change
from ..services.planning import Plan,cpm


class PlanProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: Plan
    source_baseline_id: str | None = None
    reason: str = Field(default='Initial project plan',min_length=1,max_length=2000)


def plan_approval_router(runtime):
    router = APIRouter(prefix='/api/v1/runs')

    def execute(run_id,approval_id,decision=None):
        with runtime.lock:
            runtime.plan_approval.drive(run_id,approval_id,decision)

    @router.get('/{run_id}/baselines')
    def baselines(run_id: str):
        with runtime.sessions() as session:
            run = session.get(Run,run_id)
            if not run:
                raise HTTPException(404,'Run not found')
            return [{'id':row.id,'version':row.version,'previous_id':row.previous_id,
                     'approval_id':row.approval_id,'artifact_id':row.artifact_id,
                     'effective_day':row.effective_day,'content':row.content,'content_hash':row.content_hash}
                    for row in session.scalars(select(Baseline).where(Baseline.project_id==run.project_id).order_by(Baseline.version))]

    @router.get('/{run_id}/changes')
    def changes(run_id: str):
        with runtime.sessions() as session:
            if not session.get(Run,run_id):
                raise HTTPException(404,'Run not found')
            return [{'id':row.id,'source_baseline_id':row.source_baseline_id,'artifact_id':row.artifact_id,
                     'reason':row.reason,'impact':row.impact,'status':row.status,'applied_baseline_id':row.applied_baseline_id}
                    for row in session.scalars(select(ChangeRequest).where(ChangeRequest.run_id==run_id).order_by(ChangeRequest.id))]

    @router.post('/{run_id}/plan-approvals',status_code=202)
    def propose(run_id: str,payload: PlanProposal,background: BackgroundTasks,
                idempotency_key: str=Header(min_length=1,max_length=100)):
        try:
            cpm(payload.plan)
            with runtime.lock,runtime.sessions.begin() as session:
                run = session.get(Run,run_id)
                if not run:
                    raise HTTPException(404,'Run not found')
                if run.status != 'awaiting_m3':
                    raise HTTPException(409,'Complete charter and role proposals first')
                command_key = f'plan_approval_command:{idempotency_key}'
                command = session.scalar(select(NodeReceipt).where(NodeReceipt.run_id==run_id,NodeReceipt.node==command_key))
                request = payload.model_dump(mode='json')
                if command:
                    if command.patch['request'] != request:
                        raise HTTPException(409,'Conflicting proposal replay')
                    return {'approval_id':command.patch['approval_id']}
                pending = session.scalar(select(Approval).join(Artifact,Approval.target_id==Artifact.id).where(
                    Approval.run_id==run_id,Artifact.kind=='plan',Approval.status.in_(['pending','failed'])))
                if pending:
                    raise HTTPException(409,'Resolve the existing plan approval first')
                current = session.scalar(select(Baseline).where(Baseline.project_id==run.project_id).order_by(Baseline.version.desc()).limit(1))
                if bool(current) != bool(payload.source_baseline_id):
                    raise HTTPException(409,'Existing baselines require a formal change with source_baseline_id')
                if payload.plan.version != (current.version+1 if current else 1):
                    raise HTTPException(422,'Plan must use the next baseline version')
                latest = session.scalar(select(SimulationTick).where(SimulationTick.run_id==run_id).order_by(SimulationTick.day.desc()).limit(1))
                if not current and latest:
                    raise HTTPException(409,'Cannot approve an initial baseline after draft execution; use a new project')
                day = latest.day if latest else 0
                accepted = {key for key,p in latest.snapshot['tasks'].items() if p['accepted_day'] is not None} if latest else set()
                version = (session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==run.project_id,Artifact.kind=='plan')) or 0)+1
                artifact = Artifact(project_id=run.project_id,kind='plan',version=version,author=Role.PROGRESS_COST_ANALYST,payload=payload.plan.model_dump(mode='json'))
                session.add(artifact)
                session.flush()
                change = propose_change(session,run_id,payload.source_baseline_id,artifact.id,idempotency_key,payload.reason,accepted,latest.snapshot if latest else None) if current else None
                approval = Approval(run_id=run_id,target_id=artifact.id,target_version=version)
                session.add(approval)
                session.flush()
                state = {'run_id':run_id,'project_id':run.project_id,'approval_id':approval.id,'artifact_id':artifact.id,
                         'change_id':change.id if change else None,'effective_day':day}
                session.add(NodeReceipt(run_id=run_id,node=f'plan_approval_input:{approval.id}',patch=state))
                session.add(NodeReceipt(run_id=run_id,node=command_key,patch={'request':request,'approval_id':approval.id}))
                result = {'approval_id':approval.id}
            background.add_task(execute,run_id,result['approval_id'])
            return result
        except BaselineConflict as exc:
            raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc

    @router.get('/{run_id}/plan-approvals/{approval_id}')
    def status(run_id: str,approval_id: str):
        with runtime.sessions() as session:
            approval = session.get(Approval,approval_id)
            if not approval or approval.run_id != run_id:
                raise HTTPException(404,'Approval not found')
            artifact = session.get(Artifact,approval.target_id)
            change = session.scalar(select(ChangeRequest).where(ChangeRequest.artifact_id==artifact.id,ChangeRequest.run_id==run_id))
            baseline = session.scalar(select(Baseline).where(Baseline.approval_id==approval_id))
            return {'approval_id':approval_id,'status':approval.status,'target_id':approval.target_id,
                    'target_version':approval.target_version,'plan':artifact.payload,'decision':approval.decision,
                    'baseline_id':baseline.id if baseline else None,'impact':change.impact if change else None}

    @router.post('/{run_id}/plan-approvals/{approval_id}/decision',status_code=202)
    def decide(run_id: str,approval_id: str,decision: ApprovalDecision,background: BackgroundTasks):
        with runtime.lock,runtime.sessions.begin() as session:
            approval = session.get(Approval,approval_id)
            gate = session.scalar(select(NodeReceipt).where(NodeReceipt.run_id==run_id,NodeReceipt.node==f'plan_approval_input:{approval_id}'))
            if not approval or approval.run_id != run_id or not gate:
                raise HTTPException(404,'Plan approval not found')
            if approval.target_id != decision.target_id or approval.target_version != decision.target_version:
                raise HTTPException(409,'Stale approval target')
            if approval.decision:
                if approval.decision != decision.model_dump(mode='json'):
                    raise HTTPException(409,'Approval decision already recorded differently')
                return {'approval_id':approval_id,'status':approval.status}
            snapshot = runtime.plan_approval.graph.get_state(runtime.plan_approval.config(run_id,approval_id))
            if not any(task.interrupts for task in snapshot.tasks):
                raise HTTPException(409,'Approval is not waiting for human input')
            approval.decision = decision.model_dump(mode='json')
        background.add_task(execute,run_id,approval_id,decision.model_dump(mode='json'))
        return {'approval_id':approval_id,'status':'ready'}

    @router.post('/{run_id}/plan-approvals/{approval_id}/resume',status_code=202)
    def resume(run_id: str,approval_id: str,background: BackgroundTasks):
        with runtime.sessions() as session:
            approval = session.get(Approval,approval_id)
            gate = session.scalar(select(NodeReceipt).where(NodeReceipt.run_id==run_id,NodeReceipt.node==f'plan_approval_input:{approval_id}'))
            if not approval or approval.run_id != run_id or not gate:
                raise HTTPException(404,'Plan approval not found')
            if approval.status in ['approve','reject']:
                snapshot = runtime.plan_approval.graph.get_state(runtime.plan_approval.config(run_id,approval_id))
                if not snapshot.next:
                    raise HTTPException(409,'Approval is already terminal')
        background.add_task(execute,run_id,approval_id)
        return {'approval_id':approval_id,'status':'ready'}

    return router
