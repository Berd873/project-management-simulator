import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agents.providers import MockProvider
from app.main import create_app
from app.services.reports import closure_evidence


def start(c,human=False):
    data=json.loads((Path(__file__).resolve().parents[2]/'examples/library_management/scenario.json').read_text())
    project=c.post('/api/v1/projects',json={'name':'LMS','description':'Library catalog, readers, borrowing and search','sponsor_mode':'human' if human else 'llm'}).json()['id']
    run=c.post(f'/api/v1/projects/{project}/runs',headers={'Idempotency-Key':'full'}).json()['id']
    if human:
        charter=c.get(f'/api/v1/runs/{run}').json()['approvals'][0]
        c.post(f"/api/v1/runs/{run}/approvals/{charter['id']}",json={'target_id':charter['target_id'],'target_version':charter['target_version'],'decision':'approve','reason':'Charter approved'})
    gate=c.post(f'/api/v1/runs/{run}/plan-approvals',headers={'Idempotency-Key':'plan'},json={'plan':data['plan']}).json()['approval_id']
    if human:
        decide_plan(c,run,gate)
    data['scenario'].update(formal_management=True,final_acceptance=True)
    response=c.post(f'/api/v1/runs/{run}/simulation',json={'plan':data['plan'],'scenario':data['scenario']})
    assert response.status_code==202,response.text
    if human:
        pending=next(a for a in c.get(f'/api/v1/runs/{run}').json()['approvals'] if a['status']=='pending')
        decide_plan(c,run,pending['id'])
        assert c.post(f'/api/v1/runs/{run}/simulation/resume').status_code==202
    return project,run


def decide_plan(c,run,gate):
    endpoint=f'/api/v1/runs/{run}/plan-approvals/{gate}'
    a=c.get(endpoint).json()
    response=c.post(endpoint+'/decision',json={'target_id':a['target_id'],'target_version':a['target_version'],'decision':'approve','reason':'Plan reviewed'})
    assert response.status_code==202,response.text


def test_mock_execution_feedback_and_final_report(tmp_path):
    with TestClient(create_app(f'sqlite:///{(tmp_path/"full.db").as_posix()}')) as c:
        project,run=start(c)
        result=c.get(f'/api/v1/runs/{run}/simulation').json()
        assert result['status']=='completed',result
        assert c.get(f'/api/v1/projects/{project}').json()['status']=='completed'
        report=c.get(f'/api/v1/runs/{run}/simulation/report').json()
        assert report['accepted'] and report['report']['execution_mode']=='simulation'
        assert report['report']['result_kind']=='simulated_project'
        assert report['report']['final_metrics']['ac_cents']==45000
        assert len(report['report']['scope_acceptance'])==5
        traces=c.get(f'/api/v1/runs/{run}/traces').json()
        developer=[t for t in traces if t['node'].startswith('execution:') and t['role']=='developer']
        tester=[t for t in traces if t['node'].startswith('execution:') and t['role']=='tester']
        assert len(developer)==len(tester)==9
        assert any(a['action']=='repair' for t in developer for a in t['output']['payload']['actions'])
        assert any(not r['passed'] for t in tester for r in t['output']['payload']['results'])
        assert any(t['node']=='final_acceptance' and t['valid'] for t in traces)
        assert c.post(f'/api/v1/runs/{run}/simulation/resume').status_code==409


@pytest.mark.parametrize('decision,expected',[('approve','completed'),('reject','acceptance_rejected')])
def test_human_final_acceptance_survives_restart(tmp_path,decision,expected):
    url=f'sqlite:///{(tmp_path/"human-final.db").as_posix()}'
    with TestClient(create_app(url)) as c:
        project,run=start(c,True)
        assert c.get(f'/api/v1/runs/{run}/simulation').json()['status']=='waiting_acceptance'
        assert c.post(f'/api/v1/runs/{run}/simulation/resume').status_code==409
        candidate=c.get(f'/api/v1/runs/{run}/simulation/report').json()
        assert not candidate['accepted']
    with TestClient(create_app(url)) as c:
        a=candidate['approval']
        payload={'target_id':a['target_id'],'target_version':a['target_version'],'decision':decision,'reason':'Final Sponsor review'}
        endpoint=f'/api/v1/runs/{run}/simulation/acceptance'
        assert c.post(endpoint,json={**payload,'target_version':999}).status_code==409
        assert c.post(endpoint,json=payload).status_code==202
        assert c.get(f'/api/v1/runs/{run}/simulation').json()['status']==expected
        assert c.get(f'/api/v1/runs/{run}/simulation/report').json()['accepted']==(decision=='approve')
        assert (c.get(f'/api/v1/projects/{project}').json()['status']=='completed')==(decision=='approve')
        assert c.post(endpoint,json=payload).status_code==202
        assert c.post(endpoint,json={**payload,'reason':'Conflicting review'}).status_code==409


def test_lying_tester_cannot_commit_fake_success_or_close(tmp_path):
    class LyingTester(MockProvider):
        def generate(self,context):
            result=super().generate(context)
            if context.operation=='test_results':
                result['payload']['results']=[{**r,'passed':not r['passed']} for r in result['payload']['results']]
            return result
    app=create_app(f'sqlite:///{(tmp_path/"liar.db").as_posix()}',provider=LyingTester())
    with TestClient(app) as c:
        _,run=start(c)
        result=c.get(f'/api/v1/runs/{run}/simulation').json()
        assert result['status']=='failed'
        assert result['snapshot']['day']==1  # First completed task on day two was not committed.
        assert result['metrics'][-1]['ac_cents']==5000
        with Session(app.state.engine) as session:
            with pytest.raises(ValueError,match='Open task'):
                closure_evidence(session,run)
        assert c.get(f'/api/v1/runs/{run}/simulation/report').status_code==404
