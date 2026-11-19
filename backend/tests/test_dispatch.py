import pytest
from fastapi.testclient import TestClient
from app.agents.contracts import AgentContext,validate_decision
from app.agents.providers import MockProvider
from app.domain import Role
from app.main import create_app


def context():
    return AgentContext(project_id='p',run_id='r',role=Role.PROJECT_MANAGER,brief='Library',operation='dispatch',
        facts={'eligible_task_ids':['A','B'],'suggested_task_ids':['A'],'plan':{
            'tasks':[{'id':'A','resource_id':'developer'},{'id':'B','resource_id':'developer'}],
            'resources':[{'id':'developer','capacity':1}]}})


def decision(ids):
    return {'role':'project_manager','rationale':'Coordinate work','payload':{'task_ids':ids,'summary':'Assign feasible work'}}


def test_pm_can_choose_another_feasible_priority():
    assert validate_decision(decision(['B']),context()).payload['task_ids']==['B']


@pytest.mark.parametrize('ids',[['A','B'],['unknown'],[],['A','A']])
def test_pm_cannot_bypass_capacity_eligibility_or_progress(ids):
    with pytest.raises(ValueError):
        validate_decision(decision(ids),context())


def test_invalid_pm_dispatch_stops_before_work_is_charged(tmp_path):
    class OverAllocate(MockProvider):
        def generate(self,ctx):
            result=super().generate(ctx)
            if ctx.operation=='dispatch':
                result['payload']['task_ids']=ctx.facts['eligible_task_ids']
            return result
    with TestClient(create_app(f'sqlite:///{(tmp_path/"dispatch.db").as_posix()}',provider=OverAllocate())) as c:
        p=c.post('/api/v1/projects',json={'name':'LMS','description':'Library catalog, readers and borrowing'}).json()['id']
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'dispatch'}).json()['run_id']
        assert c.get(f'/api/v1/runs/{run}/delivery').json()['status']=='failed'
        simulation=c.get(f'/api/v1/runs/{run}/simulation').json()
        assert simulation['snapshot']['day']==0
        assert simulation['metrics'][0]['ac_cents']==0
        traces=c.get(f'/api/v1/runs/{run}/traces').json()
        invalid=[t for t in traces if t['node'].endswith(':dispatch')]
        assert len(invalid)==3 and all(not t['valid'] for t in invalid)
