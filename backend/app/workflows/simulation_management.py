from copy import deepcopy
from langgraph.types import interrupt
from sqlalchemy import func,select
from ..domain import Role
from ..models import Approval,Artifact,Baseline,NodeReceipt,Project,Run
from ..services.baselines import BaselineConflict,active_baseline,propose_change,execution_transition
from ..services.planning import Plan
from ..services.rebaseline import metrics,transition
from .simulation import json_value


def prepare_change(workflow,state):
    runtime=workflow.runtime
    cached=runtime.receipt(state,'prepare_simulation_change')
    if cached is not None:
        return cached
    snapshot=state['snapshot']
    with runtime.sessions() as session:
        source=session.get(Baseline,snapshot['baseline_id'])
        old=Plan.model_validate(source.content['plan'])
    from .execution_agents import call_role
    recommendation=call_role(runtime,state['run_id'],snapshot['day'],Role.PROJECT_MANAGER,'propose_change',
        {'requested_change':'Add overdue reminders','current_plan':old.model_dump(mode='json'),
         'task_progress':snapshot['tasks'],'metrics':metrics(old,snapshot)})
    candidate=old.model_dump(mode='json')
    candidate['version']+=1
    rates={r.id:r.rate_cents_per_day for r in old.resources}
    for task in recommendation.payload['added_tasks']:
        candidate['tasks'].append({'id':task['id'],'title':task['title'],'duration_days':task['duration_days'],
            'resource_id':task['resource_id'],'budget_cents':task['duration_days']*rates[task['resource_id']]})
        candidate['dependencies'].extend({'predecessor':key,'successor':task['id'],'lag_days':0} for key in task['predecessor_ids'])
    proposed=Plan.model_validate(candidate)
    transition(old,proposed,snapshot,metrics(old,snapshot)['pv_cents'])
    with runtime.sessions.begin() as session:
        run=session.get(Run,state['run_id'])
        source=session.get(Baseline,snapshot['baseline_id'])
        if active_baseline(session,run.project_id).id!=source.id:
            raise BaselineConflict('Unexpected baseline change outside simulation control')
        spec_version=(session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==run.project_id,Artifact.kind=='change_spec')) or 0)+1
        spec=Artifact(project_id=run.project_id,kind='change_spec',version=spec_version,author=Role.PROJECT_MANAGER,payload=recommendation.payload)
        session.add(spec)
        session.flush()
        version=(session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==run.project_id,Artifact.kind=='plan')) or 0)+1
        artifact=Artifact(project_id=run.project_id,kind='plan',version=version,author=Role.PROJECT_MANAGER,payload=candidate)
        session.add(artifact)
        session.flush()
        accepted={key for key,p in snapshot['tasks'].items() if p['accepted_day'] is not None}
        change=propose_change(session,run.id,source.id,artifact.id,'simulation-overdue-reminders',recommendation.payload['reason'],accepted,snapshot)
        approval=Approval(run_id=run.id,target_id=artifact.id,target_version=version)
        session.add(approval)
        session.flush()
        inputs={'run_id':run.id,'project_id':run.project_id,'approval_id':approval.id,'artifact_id':artifact.id,
                'change_id':change.id,'effective_day':snapshot['day'],'change_spec_id':spec.id}
        session.add(NodeReceipt(run_id=run.id,node=f'plan_approval_input:{approval.id}',patch=inputs))
        return runtime.save(session,state,'prepare_simulation_change',{'change_approval_id':approval.id})


def review_change(workflow,state):
    runtime=workflow.runtime
    cached=runtime.receipt(state,'review_simulation_change')
    if cached is not None:
        return cached
    approval_id=state['change_approval_id']
    with runtime.sessions() as session:
        run=session.get(Run,state['run_id'])
        human=session.get(Project,run.project_id).sponsor_mode.value=='human'
    runtime.plan_approval.drive(state['run_id'],approval_id)
    if human:
        interrupt({'kind':'change_approval','approval_id':approval_id})
    with runtime.sessions.begin() as session:
        approval=session.get(Approval,approval_id)
        if approval.status not in ['approve','reject']:
            raise BaselineConflict('Change approval is not terminal')
        snapshot=deepcopy(state['snapshot'])
        if approval.status=='approve':
            baseline=session.scalar(select(Baseline).where(Baseline.approval_id==approval_id))
            if not baseline or baseline.previous_id!=snapshot['baseline_id']:
                raise BaselineConflict('Change baseline does not follow simulation baseline')
            source=session.get(Baseline,snapshot['baseline_id'])
            old,proposed=Plan.model_validate(source.content['plan']),Plan.model_validate(baseline.content['plan'])
            if baseline.content.get('execution_transition')!=execution_transition(old,proposed,snapshot,source.id):
                raise BaselineConflict('Simulation transition no longer matches the approved remaining plan')
            snapshot=transition(old,proposed,snapshot,metrics(old,snapshot)['pv_cents'])
            snapshot['baseline_id']=baseline.id
        else:
            snapshot['change_resolved']=True
        return runtime.save(session,state,'review_simulation_change',{'snapshot':json_value(snapshot)})
