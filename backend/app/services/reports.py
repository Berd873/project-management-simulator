from sqlalchemy import select
from ..models import AgentExecution,Approval,Artifact,Baseline,ChangeRequest,Project,Run,SimulationRun,SimulationTick


def closure_evidence(session,run_id):
    run=session.get(Run,run_id)
    simulation=session.get(SimulationRun,run_id)
    latest=session.scalar(select(SimulationTick).where(SimulationTick.run_id==run_id).order_by(SimulationTick.day.desc()).limit(1))
    if not run or not simulation or not latest or not simulation.scenario.get('formal_management'):
        raise ValueError('Formal simulation evidence is required')
    snapshot=latest.snapshot
    if any(p['accepted_day'] is None or p['rework_left'] for p in snapshot['tasks'].values()):
        raise ValueError('Open task or blocking simulated defect prevents closure')
    baselines=session.scalars(select(Baseline).where(Baseline.project_id==run.project_id).order_by(Baseline.version)).all()
    if not baselines or baselines[-1].id!=snapshot.get('baseline_id'):
        raise ValueError('Final execution does not match active baseline')
    if session.scalar(select(Approval).join(Artifact,Approval.target_id==Artifact.id).where(
        Approval.run_id==run_id,Artifact.kind=='plan',Approval.status.not_in(['approve','reject']))):
        raise ValueError('Unresolved plan approval prevents closure')
    changes=session.scalars(select(ChangeRequest).where(ChangeRequest.run_id==run_id).order_by(ChangeRequest.id)).all()
    if any(change.status not in ['applied','rejected'] for change in changes):
        raise ValueError('Unresolved change prevents closure')
    project=session.get(Project,run.project_id)
    plan=baselines[-1].content['plan']
    if set(snapshot['tasks'])!={task['id'] for task in plan['tasks']}:
        raise ValueError('Scope coverage mismatch')
    specifications=session.scalars(select(Artifact).where(Artifact.project_id==project.id,
        Artifact.kind.in_(['requirements_analyst','change_spec'])).order_by(Artifact.kind,Artifact.version)).all()
    criteria={}
    for specification in specifications:
        items=specification.payload.get('tasks',specification.payload.get('added_tasks',[]))
        criteria.update({task['id']:task['acceptance_criteria'] for task in items})
    if any(task['id'] not in criteria for task in plan['tasks']):
        raise ValueError('Final scope lacks requirement acceptance criteria')
    analysis=session.scalar(select(AgentExecution).where(AgentExecution.run_id==run_id,AgentExecution.valid.is_(True),
        AgentExecution.node==f"execution:{snapshot['day']}:progress_cost_analyst:monitor").order_by(AgentExecution.attempt.desc()).limit(1))
    return {'title':'模拟项目结项与管理报告','execution_mode':'simulation','result_kind':'simulated_project',
        'project_id':project.id,'project_name':project.name,'run_id':run_id,'seed':simulation.seed,
        'scenario_version':simulation.scenario['version'],'engine_version':snapshot['engine_version'],
        'provider_versions':sorted(set(session.scalars(select(AgentExecution.provider).where(AgentExecution.run_id==run_id)))),
        'prompt_versions':sorted(set(session.scalars(select(AgentExecution.prompt_version).where(AgentExecution.run_id==run_id)))),
        'agent_schema_version':1,'workflow_version':'simulation-v1',
        'specification_refs':[{'id':a.id,'kind':a.kind,'version':a.version} for a in specifications],
        'performance_analysis':analysis.output['payload'] if analysis else None,
        'simulation_days':snapshot['day'],'final_baseline_id':baselines[-1].id,'final_metrics':latest.metrics,
        'baseline_history':[{'id':b.id,'version':b.version,'effective_day':b.effective_day,'hash':b.content_hash} for b in baselines],
        'change_history':[{'id':c.id,'status':c.status,'reason':c.reason,'impact':c.impact,'applied_baseline_id':c.applied_baseline_id} for c in changes],
        'scope_acceptance':[{'task_id':task['id'],'title':task['title'],'accepted_day':snapshot['tasks'][task['id']]['accepted_day'],
                            'acceptance_criteria':criteria[task['id']],
                            'simulated_test_attempts':snapshot['tasks'][task['id']]['attempts']} for task in plan['tasks']],
        'management_lessons':['Resource constraints and rework explain variance from dependency-only CPM.',
                              'Approved changes retain baseline history and historical execution metrics.'],
        'limitations':['All deliverables and test outcomes concern simulation; no LMS source code was executed.']}
