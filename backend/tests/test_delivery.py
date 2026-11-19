import pytest
from fastapi.testclient import TestClient
from app.agents.providers import MockProvider
from app.main import create_app


def project(c,human=False):
    return c.post('/api/v1/projects',json={'name':'Library Management System','description':'Library catalog management, reader management, borrowing, returns and search.',
        'sponsor_mode':'human' if human else 'llm','llm_mode':'mock','seed':42}).json()['id']


def test_no_key_full_automatic_library_delivery_and_restart(tmp_path,monkeypatch):
    monkeypatch.delenv('LLM_API_KEY',raising=False)
    url=f'sqlite:///{(tmp_path/"automatic.db").as_posix()}'
    with TestClient(create_app(url)) as c:
        p=project(c)
        response=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'demo'})
        assert response.status_code==202,response.text
        run=response.json()['run_id']
        endpoint=f'/api/v1/runs/{run}/delivery'
        result=c.get(endpoint).json()
        assert result['status']=='completed',result
        assert c.get(f'/api/v1/projects/{p}').json()['status']=='completed'
        report=c.get(f'/api/v1/runs/{run}/simulation/report').json()
        assert report['accepted'] and report['report']['simulation_days']==9
        assert report['report']['final_metrics']['ev_cents']==40000
        assert report['report']['final_metrics']['ac_cents']==45000
        artifacts=c.get(f'/api/v1/runs/{run}/artifacts').json()
        srs=next(a for a in artifacts if a['kind']=='requirements_analyst')
        estimates=next(a for a in artifacts if a['kind']=='planning_estimates')
        plan=next(a for a in artifacts if a['kind']=='plan' and a['payload']['version']==1)
        assert {t['id'] for t in srs['payload']['tasks']}=={t['id'] for t in plan['payload']['tasks']}
        assert sum(t['budget_cents'] for t in plan['payload']['tasks'])==30000
        assert len(estimates['payload']['tasks'])==4
        assert next(a for a in artifacts if a['kind']=='change_spec')['payload']['added_tasks'][0]['acceptance_criteria']
        traces=c.get(f'/api/v1/runs/{run}/traces').json()
        assert all(t['prompt_version']=='mock-decisions-v6' for t in traces)
        assert len([t for t in traces if t['node'].endswith(':dispatch')])==9
        assert '关键任务' in report['report']['performance_analysis']['assessment']
        assert any('成本' in risk for risk in report['report']['performance_analysis']['risks'])
        assert any(t['node'].endswith(':estimate_plan') for t in traces)
        assert any(t['node'].endswith(':propose_change') and t['role']=='project_manager' for t in traces)
        count=len(traces)
        assert c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'demo'}).json()['run_id']==run
        assert c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'different'}).status_code==409
        assert len(c.get(f'/api/v1/runs/{run}/traces').json())==count
    with TestClient(create_app(url)) as c:
        assert c.get(endpoint).json()['status']=='completed'
        assert c.get(f'/api/v1/runs/{run}/simulation/report').json()==report


def test_human_delivery_four_gates_recover_between_app_instances(tmp_path):
    url=f'sqlite:///{(tmp_path/"human-pipeline.db").as_posix()}'
    with TestClient(create_app(url)) as c:
        p=project(c,True)
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'human'}).json()['run_id']
    kinds=[]
    for _ in range(4):
        with TestClient(create_app(url)) as c:
            endpoint=f'/api/v1/runs/{run}/delivery'
            status=c.get(endpoint).json()
            assert status['status']=='waiting_approval',status
            assert c.post(endpoint+'/resume').status_code==409
            pending=status['pending_approvals']
            assert len(pending)==1,pending
            a=pending[0]
            kinds.append(a['kind'])
            payload={'target_id':a['target_id'],'target_version':a['target_version'],'decision':'approve','reason':'Human review accepted'}
            if a['kind']=='project_manager':
                decision_path=f"/api/v1/runs/{run}/approvals/{a['id']}"
            elif a['kind']=='plan':
                decision_path=f"/api/v1/runs/{run}/plan-approvals/{a['id']}/decision"
            else:
                assert a['kind']=='closure_candidate'
                decision_path=f'/api/v1/runs/{run}/simulation/acceptance'
            assert c.post(decision_path,json=payload).status_code==202
            assert c.post(endpoint+'/resume').status_code==202
    with TestClient(create_app(url)) as c:
        assert c.get(f'/api/v1/runs/{run}/delivery').json()['status']=='completed'
        assert c.get(f'/api/v1/runs/{run}/simulation/report').json()['accepted']
    assert kinds==['project_manager','plan','plan','closure_candidate']


def test_rejected_charter_does_not_generate_plan_or_simulation(tmp_path):
    with TestClient(create_app(f'sqlite:///{(tmp_path/"reject.db").as_posix()}')) as c:
        p=project(c,True)
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'rejected'}).json()['run_id']
        endpoint=f'/api/v1/runs/{run}/delivery'
        a=c.get(endpoint).json()['pending_approvals'][0]
        c.post(f"/api/v1/runs/{run}/approvals/{a['id']}",json={'target_id':a['target_id'],'target_version':a['target_version'],'decision':'reject','reason':'Objective unclear'})
        assert c.post(endpoint+'/resume').status_code==202
        assert c.get(endpoint).json()['status']=='rejected'
        assert c.get(f'/api/v1/runs/{run}/simulation').status_code==404
        assert c.get(f'/api/v1/runs/{run}/baselines').json()==[]
        assert c.post(endpoint+'/resume').status_code==409


def test_incomplete_agent_estimates_fail_before_baseline(tmp_path):
    class MissingEstimate(MockProvider):
        def generate(self,context):
            result=super().generate(context)
            if context.operation=='estimate_plan':
                result['payload']['tasks'].pop()
            return result
    with TestClient(create_app(f'sqlite:///{(tmp_path/"bad-estimate.db").as_posix()}',provider=MissingEstimate())) as c:
        p=project(c)
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'invalid'}).json()['run_id']
        assert c.get(f'/api/v1/runs/{run}/delivery').json()['status']=='failed'
        assert c.get(f'/api/v1/runs/{run}/baselines').json()==[]
        traces=c.get(f'/api/v1/runs/{run}/traces').json()
        failed=[t for t in traces if t['node'].endswith(':estimate_plan')]
        assert len(failed)==3 and all(not t['valid'] for t in failed)
