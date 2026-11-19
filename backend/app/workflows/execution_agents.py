from ..agents.contracts import AgentContext,validate_decision
from ..agents.providers import MockProvider,RealProvider
from ..domain import Role
from ..models import Artifact,Project,Run
from sqlalchemy import select
from ..services.simulation import eligible_assignments,ready_assignments
from .simulation import json_value


def call_role(runtime,run_id,day,role,operation,facts):
    with runtime.sessions() as session:
        run=session.get(Run,run_id)
        project=session.get(Project,run.project_id)
        specifications=session.scalars(select(Artifact).where(Artifact.project_id==project.id,
            Artifact.kind.in_(['requirements_analyst','change_spec'])).order_by(Artifact.kind,Artifact.version)).all()
        context=AgentContext(project_id=project.id,run_id=run_id,role=role,brief=project.description,
                             operation=operation,facts=json_value(facts),
                             artifact_refs={f'{a.kind}:{a.version}':a.id for a in specifications},
                             artifacts={f'{a.kind}:{a.version}':a.payload for a in specifications})
        provider=runtime.provider or (MockProvider() if project.llm_mode.value=='mock' else RealProvider())
    return runtime.validated_call({'run_id':run_id},f'execution:{day}:{role.value}:{operation}',role,provider,
        context.model_dump(mode='json'),lambda:provider.generate(context),lambda raw:validate_decision(raw,context))


def dispatch(runtime,run_id,plan,snapshot):
    return call_role(runtime,run_id,snapshot['day']+1,Role.PROJECT_MANAGER,'dispatch',
        {'eligible_task_ids':eligible_assignments(plan,snapshot),'suggested_task_ids':ready_assignments(plan,snapshot),
         'plan':plan.model_dump(mode='json'),'task_progress':snapshot['tasks']})


def developer(runtime,run_id,snapshot,assignments):
    expected=[{'task_id':key,'action':'repair' if snapshot['tasks'][key]['rework_left'] else 'develop'} for key in assignments]
    return call_role(runtime,run_id,snapshot['day']+1,Role.DEVELOPER,'execute',
                     {'expected_actions':expected,'task_progress':snapshot['tasks']})


def tester_and_analyst(runtime,run_id,snapshot,events,metrics,schedule):
    expected=[{'task_id':e['task_id'],'passed':e['kind']=='simulated_test_passed','attempt':e['attempt']}
              for e in events if e['kind'] in ['simulated_test_passed','simulated_test_failed']]
    report=call_role(runtime,run_id,snapshot['day'],Role.TESTER,'test_results',{'expected_results':expected,'engine_events':events})
    analysis=call_role(runtime,run_id,snapshot['day'],Role.PROGRESS_COST_ANALYST,'monitor',
                       {'metrics':metrics,'engine_events':events,'cpm':schedule,'remaining_forecast':snapshot.get('remaining_forecast',{})})
    return report,analysis
