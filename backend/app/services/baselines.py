"""Transactional baseline primitives. Workflow nodes own the transaction and routing."""
import hashlib
import json

from sqlalchemy import select

from ..agents.contracts import ApprovalDecision
from ..models import Approval, Artifact, Baseline, ChangeRequest, Run,SimulationTick
from .planning import Plan, cpm


class BaselineConflict(ValueError):
    pass


def active_baseline(session, project_id):
    return session.scalar(select(Baseline).where(Baseline.project_id == project_id).order_by(Baseline.version.desc()).limit(1))


def analyze_change(source: Plan, proposed: Plan, accepted_ids: set[str]) -> dict:
    old = {task.id:task for task in source.tasks}
    new = {task.id:task for task in proposed.tasks}
    if not accepted_ids <= old.keys():
        raise BaselineConflict('Unknown accepted task')
    if proposed.version != source.version+1:
        raise BaselineConflict('Plan must advance exactly one version')
    for key in accepted_ids:
        if key not in new or new[key] != old[key]:
            raise BaselineConflict('Accepted task scope/value cannot be rewritten')
        old_edges = {e.model_dump_json() for e in source.dependencies if e.successor == key}
        new_edges = {e.model_dump_json() for e in proposed.dependencies if e.successor == key}
        if old_edges != new_edges:
            raise BaselineConflict('Accepted task dependencies cannot be rewritten')
    before, after = cpm(source), cpm(proposed)
    old_bac = sum(t.budget_cents for t in source.tasks)
    new_bac = sum(t.budget_cents for t in proposed.tasks)
    result = {'source_plan_version':source.version,'proposed_plan_version':proposed.version,
            'added_task_ids':sorted(new.keys()-old.keys()),'removed_task_ids':sorted(old.keys()-new.keys()),
            'changed_task_ids':sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
            'source_bac_cents':old_bac,'proposed_bac_cents':new_bac,'delta_bac_cents':new_bac-old_bac,
            'source_duration_days':before['duration_days'],'proposed_duration_days':after['duration_days'],
            'delta_duration_days':after['duration_days']-before['duration_days'],
            'proposed_schedule':after,'accepted_task_ids':sorted(accepted_ids),
            'schedule_assumption':'Dependency-only CPM; resource waiting and remaining effort require runtime forecasting'}
    return json.loads(json.dumps(result))


def snapshot_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def execution_transition(source: Plan, proposed: Plan, snapshot: dict, baseline_id: str):
    from .rebaseline import metrics,transition
    if snapshot.get('baseline_id')!=baseline_id:
        raise BaselineConflict('Execution snapshot does not bind the source baseline')
    migrated=transition(source,proposed,snapshot,metrics(source,snapshot)['pv_cents'])
    return {'source_baseline_id':baseline_id,'source_day':snapshot['day'],'source_snapshot_hash':snapshot_hash(snapshot),
            'pv_anchor':migrated['pv_anchor'],'remaining_forecast':migrated['remaining_forecast']}


def propose_change(session, run_id, source_id, artifact_id, request_key, reason, accepted_ids,execution_snapshot=None):
    run, source, artifact = session.get(Run,run_id), session.get(Baseline,source_id), session.get(Artifact,artifact_id)
    if not run or not source or not artifact or source.project_id != run.project_id or artifact.project_id != run.project_id:
        raise BaselineConflict('Missing or cross-project change reference')
    existing = session.scalar(select(ChangeRequest).where(ChangeRequest.run_id == run_id,ChangeRequest.request_key == request_key))
    if existing:
        if (existing.source_baseline_id,existing.artifact_id,existing.reason) != (source_id,artifact_id,reason):
            raise BaselineConflict('Conflicting change request replay')
        return existing
    if active_baseline(session,run.project_id).id != source_id:
        raise BaselineConflict('Source baseline is stale')
    if not reason.strip():
        raise BaselineConflict('Change requires a reason')
    if artifact.kind != 'plan':
        raise BaselineConflict('Change artifact must be a plan')
    candidate = Plan.model_validate(artifact.payload)
    impact = analyze_change(Plan.model_validate(source.content['plan']),candidate,accepted_ids)
    if execution_snapshot is not None:
        tick=session.scalar(select(SimulationTick).where(SimulationTick.run_id==run_id,SimulationTick.day==execution_snapshot['day']))
        if not tick or snapshot_hash(tick.snapshot)!=snapshot_hash(execution_snapshot):
            raise BaselineConflict('Execution snapshot is not the persisted source tick')
        actual_accepted={key for key,p in tick.snapshot['tasks'].items() if p['accepted_day'] is not None}
        if actual_accepted!=accepted_ids:
            raise BaselineConflict('Accepted tasks do not match persisted execution')
        impact['execution_transition']=execution_transition(Plan.model_validate(source.content['plan']),candidate,tick.snapshot,source_id)
    row = ChangeRequest(run_id=run_id,source_baseline_id=source_id,artifact_id=artifact_id,request_key=request_key,
                        reason=reason,impact=impact)
    session.add(row)
    session.flush()
    return row


def commit_baseline(session, run_id, artifact_id, approval_id, effective_day=0, change_id=None):
    run, artifact, approval = session.get(Run,run_id), session.get(Artifact,artifact_id), session.get(Approval,approval_id)
    if not run or not artifact or not approval:
        raise BaselineConflict('Missing baseline reference')
    if artifact.project_id != run.project_id or approval.run_id != run_id or artifact.kind != 'plan':
        raise BaselineConflict('Cross-project or invalid plan approval')
    decision = ApprovalDecision.model_validate(approval.decision or {})
    if approval.status != 'approve' or decision.decision != 'approve':
        raise BaselineConflict('Plan approval is required')
    if approval.target_id != artifact_id or decision.target_id != artifact_id or approval.target_version != artifact.version or decision.target_version != artifact.version:
        raise BaselineConflict('Approval does not bind this artifact version')
    if type(effective_day) is not int or effective_day < 0:
        raise BaselineConflict('Invalid effective day')
    plan = Plan.model_validate(artifact.payload)
    existing = session.scalar(select(Baseline).where(Baseline.approval_id == approval_id))
    if existing:
        if existing.run_id != run_id or existing.artifact_id != artifact_id or existing.effective_day != effective_day:
            raise BaselineConflict('Conflicting baseline replay')
        if change_id:
            change = session.get(ChangeRequest,change_id)
            if not change or change.applied_baseline_id != existing.id:
                raise BaselineConflict('Conflicting change replay')
        elif existing.previous_id:
            raise BaselineConflict('Change reference is required')
        return existing
    current = active_baseline(session,run.project_id)
    change = None
    if current:
        change = session.get(ChangeRequest,change_id) if change_id else None
        if not change or change.run_id != run_id or change.source_baseline_id != current.id or change.artifact_id != artifact_id or change.status != 'proposed':
            raise BaselineConflict('A current formal change request is required')
        if effective_day < current.effective_day:
            raise BaselineConflict('Cannot backdate a changed baseline')
        recomputed = analyze_change(Plan.model_validate(current.content['plan']),plan,set(change.impact['accepted_task_ids']))
        context=change.impact.get('execution_transition')
        if context:
            tick=session.scalar(select(SimulationTick).where(SimulationTick.run_id==run_id,SimulationTick.day==context['source_day']))
            if not tick or effective_day!=context['source_day']:
                raise BaselineConflict('Change must take effect at the reviewed execution day')
            actual_accepted={key for key,p in tick.snapshot['tasks'].items() if p['accepted_day'] is not None}
            if actual_accepted!=set(change.impact['accepted_task_ids']):
                raise BaselineConflict('Reviewed execution acceptance no longer matches')
            recomputed['execution_transition']=execution_transition(Plan.model_validate(current.content['plan']),plan,tick.snapshot,current.id)
        if recomputed != change.impact:
            raise BaselineConflict('Impact analysis no longer matches candidate plan')
    elif change_id or effective_day != 0:
        raise BaselineConflict('Initial baseline must begin at day zero')
    version = current.version+1 if current else 1
    if plan.version != version:
        raise BaselineConflict('Plan and baseline versions must match')
    content = {'plan':plan.model_dump(mode='json'),'schedule':cpm(plan),'effective_day':effective_day,
               'impact':change.impact if change else None,
               'execution_transition':change.impact.get('execution_transition') if change else None}
    content_hash = hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    row = Baseline(project_id=run.project_id,run_id=run_id,version=version,previous_id=current.id if current else None,
                   approval_id=approval_id,artifact_id=artifact_id,effective_day=effective_day,content=content,content_hash=content_hash)
    session.add(row)
    session.flush()
    if change:
        change.status, change.applied_baseline_id = 'applied', row.id
    return row
