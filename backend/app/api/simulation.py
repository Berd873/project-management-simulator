from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ..models import Approval, Artifact, Project, Run, SimulationRun, SimulationTick
from ..services.planning import Plan, cpm
from ..services.simulation import Scenario
from ..workflows.simulation import json_value
from ..services.baselines import active_baseline
from ..agents.contracts import ApprovalDecision
from ..models import Artifact


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: Plan
    scenario: Scenario


def simulation_router(runtime):
    router = APIRouter(prefix='/api/v1/runs')

    def enforce_plan_approval(session,run,plan):
        baseline = active_baseline(session,run.project_id)
        gate = session.scalar(select(Approval).join(Artifact,Approval.target_id==Artifact.id).where(
            Approval.run_id==run.id,Artifact.kind=='plan').order_by(Artifact.version.desc()).limit(1))
        if gate and (gate.status in ['pending','failed'] or baseline is None):
            raise HTTPException(409,'Resolve formal plan approval before executing')
        if baseline and baseline.content['plan'] != plan:
            raise HTTPException(409,'Simulation must use the approved baseline plan')

    def execute(run_id):
        with runtime.lock:
            runtime.simulation.drive(run_id)

    @router.post('/{run_id}/simulation', status_code=202)
    def start(run_id: str, payload: SimulationRequest, background: BackgroundTasks):
        try:
            schedule = cpm(payload.plan)
            if payload.scenario.final_acceptance and not payload.scenario.formal_management:
                raise ValueError('Final acceptance requires formal management')
            if not set(payload.scenario.forced_first_test_failures) <= {t.id for t in payload.plan.tasks}:
                raise ValueError('Unknown task in scenario')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        plan = payload.plan.model_dump(mode='json')
        scenario = payload.scenario.model_dump(mode='json')
        with runtime.lock, runtime.sessions.begin() as session:
            run = session.get(Run, run_id)
            if not run:
                raise HTTPException(404,'Run not found')
            existing = session.get(SimulationRun, run_id)
            if existing:
                if existing.plan != plan or existing.scenario != scenario:
                    raise HTTPException(409,'Simulation inputs are immutable; conflicting replay')
                return {'run_id':run_id,'status':existing.status}
            if run.status != 'awaiting_m3':
                raise HTTPException(409,'Agent proposal workflow must finish first')
            enforce_plan_approval(session,run,plan)
            if payload.scenario.formal_management and active_baseline(session,run.project_id) is None:
                raise HTTPException(409,'Formal management requires an approved initial baseline')
            project = session.get(Project, run.project_id)
            session.add(SimulationRun(run_id=run_id,plan=plan,scenario=scenario,
                                      seed=project.seed,schedule=json_value(schedule)))
        background.add_task(execute,run_id)
        return {'run_id':run_id,'status':'ready'}

    @router.post('/{run_id}/simulation/resume', status_code=202)
    def resume(run_id: str, background: BackgroundTasks):
        with runtime.lock, runtime.sessions.begin() as session:
            row = session.get(SimulationRun,run_id)
            if not row:
                raise HTTPException(404,'Simulation not found')
            if row.status not in ['failed','ready','waiting_change','waiting_acceptance']:
                raise HTTPException(409,'Simulation is already finished')
            if row.status=='waiting_acceptance':
                state=runtime.simulation.graph.get_state(runtime.simulation.config(run_id,row.scenario['max_days'])).values
                approval=session.get(Approval,state.get('closure_approval_id'))
                if not approval or not approval.decision:
                    raise HTTPException(409,'Submit final Sponsor acceptance first')
            run=session.get(Run,run_id)
            baseline=active_baseline(session,run.project_id)
            enforce_plan_approval(session,run,baseline.content['plan'] if row.scenario.get('formal_management') and baseline else row.plan)
            row.status = 'ready'
        background.add_task(execute,run_id)
        return {'run_id':run_id,'status':'ready'}

    @router.get('/{run_id}/simulation')
    def status(run_id: str):
        with runtime.sessions() as session:
            row = session.get(SimulationRun,run_id)
            if not row:
                raise HTTPException(404,'Simulation not found')
            ticks = session.scalars(select(SimulationTick).where(SimulationTick.run_id == run_id).order_by(SimulationTick.day)).all()
            run=session.get(Run,run_id)
            baseline=active_baseline(session,run.project_id)
            return {'run_id':run_id,'status':row.status,'error':row.error,'seed':row.seed,
                'execution_mode':'simulation','plan_status':'approved' if baseline else 'draft_unapproved','plan':row.plan,
                'current_plan':baseline.content['plan'] if baseline else row.plan,'baseline_id':baseline.id if baseline else None,
                'scenario':row.scenario,'schedule':row.schedule,
                'snapshot':ticks[-1].snapshot if ticks else None,
                'metrics':[t.metrics for t in ticks],
                'ticks':[{'day':t.day,'assignments':t.assignments,'events':t.events} for t in ticks]}

    @router.get('/{run_id}/simulation/report')
    def report(run_id: str):
        with runtime.sessions() as session:
            row=session.get(SimulationRun,run_id)
            if not row:
                raise HTTPException(404,'Simulation not found')
            state=runtime.simulation.graph.get_state(runtime.simulation.config(run_id,row.scenario['max_days'])).values
            artifact_id=state.get('report_id') or state.get('closure_artifact_id')
            if not artifact_id:
                raise HTTPException(404,'Closure report is not ready')
            artifact=session.get(Artifact,artifact_id)
            approval=session.get(Approval,state['closure_approval_id'])
            return {'status':row.status,'accepted':row.status=='completed','report':artifact.payload,
                    'approval':{'id':approval.id,'target_id':approval.target_id,'target_version':approval.target_version,'status':approval.status,'decision':approval.decision}}

    @router.post('/{run_id}/simulation/acceptance',status_code=202)
    def accept(run_id: str,decision: ApprovalDecision,background: BackgroundTasks):
        with runtime.lock,runtime.sessions.begin() as session:
            row=session.get(SimulationRun,run_id)
            if not row:
                raise HTTPException(404,'Simulation not found')
            state=runtime.simulation.graph.get_state(runtime.simulation.config(run_id,row.scenario['max_days'])).values
            approval=session.get(Approval,state.get('closure_approval_id')) if state.get('closure_approval_id') else None
            if not approval:
                raise HTTPException(409,'Final acceptance is not ready')
            if (decision.target_id,decision.target_version)!=(approval.target_id,approval.target_version):
                raise HTTPException(409,'Final acceptance target/version mismatch')
            if approval.decision:
                if approval.decision!=decision.model_dump(mode='json'):
                    raise HTTPException(409,'Sponsor already submitted a different decision')
                return {'run_id':run_id,'status':row.status}
            if row.status!='waiting_acceptance':
                raise HTTPException(409,'Simulation is not waiting for final acceptance')
            approval.decision=decision.model_dump(mode='json')
        background.add_task(execute,run_id)
        return {'run_id':run_id,'status':'ready'}
    return router
