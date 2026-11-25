import json
from app.agents.providers import RealProvider
from app.agents.contracts import AgentContext,validate_decision
from app.domain import Role
import pytest

def test_real_provider_feeds_business_error_into_next_bounded_attempt():
    provider=RealProvider.__new__(RealProvider)
    context=AgentContext(project_id='p',run_id='r',role=Role.PROJECT_MANAGER,brief='ticketing',operation='dispatch',facts={
        'eligible_task_ids':['2'],'suggested_task_ids':['2'],'plan':{'tasks':[{'id':'2','resource_id':'backend'}],'resources':[{'id':'backend','capacity':1}]}})
    calls=[]
    def request(schema,content):
        inputs=json.loads(content);calls.append(inputs)
        if len(calls)==2:assert 'eligible' in inputs['validation_feedback']
        return {'role':'project_manager','rationale':'dispatch','payload':{'task_ids':['invalid'] if len(calls)==1 else ['2'],'summary':'assign'}}
    provider.request=request
    with pytest.raises(ValueError):validate_decision(provider.generate(context),context)
    assert validate_decision(provider.generate(context),context).payload['task_ids']==['2']
    assert provider.validation_feedback is None


def test_explicit_repair_batch_preserves_failed_attempts_and_cost(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.agents.providers import MockProvider
    class BadDeveloper(MockProvider):
        def generate(self,context):
            raw=super().generate(context)
            if context.operation=='execute':raw['evidence_refs']=['nonexistent']
            return raw
    app=create_app(f"sqlite:///{(tmp_path/'repair.db').as_posix()}",provider=BadDeveloper())
    with TestClient(app) as c:
        p=c.post('/api/v1/projects',json={'name':'Library','description':'Library management'}).json()['id']
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'repair'}).json()['run_id']
        prefix=f'/api/v1/runs/{run}'
        assert c.get(prefix+'/delivery').json()['status']=='failed'
        before=c.get(prefix+'/traces').json()
        failed=[t for t in before if t['node']=='execution:1:developer:execute']
        assert len(failed)==3 and all(not t['valid'] for t in failed)
        app.state.runtime.provider=MockProvider()
        app.state.runtime.repair_nodes={'execution:1:developer:execute'}
        assert c.post(prefix+'/delivery/resume').status_code==202
        assert c.get(prefix+'/delivery').json()['status']=='completed'
        after=c.get(prefix+'/traces').json()
        assert [t for t in after if t['node']=='execution:1:developer:execute']==failed
        assert len([t for t in after if t['node']=='execution:1:developer:execute:repair1' and t['valid']])==1
        assert c.get(prefix+'/simulation/report').json()['report']['final_metrics']['ac_cents']==45000
