from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func,select
from sqlalchemy.orm import Session

from app.agents.providers import MockProvider
from app.main import create_app
from app.models import Baseline,ChangeRequest


def plan():
    return json.loads((Path(__file__).resolve().parents[2]/'examples/library_management/scenario.json').read_text())['plan']


def run(client,human=False):
    project=client.post('/api/v1/projects',json={'name':'LMS','description':'Library scope','sponsor_mode':'human' if human else 'llm'}).json()['id']
    run_id=client.post(f'/api/v1/projects/{project}/runs',headers={'Idempotency-Key':'setup'}).json()['id']
    if human:
        charter=client.get(f'/api/v1/runs/{run_id}').json()['approvals'][0]
        response=client.post(f"/api/v1/runs/{run_id}/approvals/{charter['id']}",json={
            'target_id':charter['target_id'],'target_version':charter['target_version'],'decision':'approve','reason':'Charter reviewed'})
        assert response.status_code==202
    return run_id


def propose(client,run_id,candidate,key='initial',source=None):
    return client.post(f'/api/v1/runs/{run_id}/plan-approvals',headers={'Idempotency-Key':key},
        json={'plan':candidate,'source_baseline_id':source,'reason':'Scope proposal'})


def test_mock_initial_and_formal_change_graph(tmp_path):
    app=create_app(f'sqlite:///{(tmp_path/"gates.db").as_posix()}')
    with TestClient(app) as c:
        run_id=run(c)
        response=propose(c,run_id,plan())
        assert response.status_code==202,response.text
        gate=response.json()['approval_id']
        initial=c.get(f'/api/v1/runs/{run_id}/plan-approvals/{gate}').json()
        assert initial['status']=='approve' and initial['baseline_id']
        assert propose(c,run_id,plan()).json()['approval_id']==gate
        candidate=deepcopy(plan())
        candidate['version']=2
        candidate['tasks'].append({'id':'5','title':'Reminders','duration_days':2,'budget_cents':10000,'resource_id':'developer'})
        candidate['dependencies'].append({'predecessor':'3','successor':'5'})
        assert propose(c,run_id,candidate,'bypass').status_code==409
        changed=propose(c,run_id,candidate,'change',initial['baseline_id'])
        assert changed.status_code==202,changed.text
        result=c.get(f"/api/v1/runs/{run_id}/plan-approvals/{changed.json()['approval_id']}").json()
        assert result['status']=='approve' and result['baseline_id']!=initial['baseline_id']
        assert result['impact']['delta_bac_cents']==10000
        assert [b['version'] for b in c.get(f'/api/v1/runs/{run_id}/baselines').json()]==[1,2]
        assert c.get(f'/api/v1/runs/{run_id}/changes').json()[0]['applied_baseline_id']==result['baseline_id']
        with Session(app.state.engine) as s:
            assert s.scalar(select(func.count()).select_from(Baseline))==2
            assert s.scalar(select(ChangeRequest)).status=='applied'
        scenario={'version':'test'}
        assert c.post(f'/api/v1/runs/{run_id}/simulation',json={'plan':plan(),'scenario':scenario}).status_code==409


def test_human_plan_gate_restart_and_rejection(tmp_path):
    url=f'sqlite:///{(tmp_path/"human-plan.db").as_posix()}'
    with TestClient(create_app(url)) as c:
        run_id=run(c,True)
        gate=propose(c,run_id,plan()).json()['approval_id']
        endpoint=f'/api/v1/runs/{run_id}/plan-approvals/{gate}'
        pending=c.get(endpoint).json()
        assert pending['status']=='pending' and pending['baseline_id'] is None
        assert c.post(f'/api/v1/runs/{run_id}/simulation',json={'plan':plan(),'scenario':{}}).status_code==409
    app=create_app(url)
    with TestClient(app) as c:
        decision={'target_id':pending['target_id'],'target_version':pending['target_version'],'decision':'reject','reason':'Revise scope'}
        assert c.post(endpoint+'/decision',json={**decision,'target_version':999}).status_code==409
        assert c.post(endpoint+'/decision',json=decision).status_code==202
        assert c.get(endpoint).json()['status']=='reject'
        assert c.post(f'/api/v1/runs/{run_id}/simulation',json={'plan':plan(),'scenario':{}}).status_code==409
        assert c.post(endpoint+'/decision',json=decision).status_code==202
        assert c.post(endpoint+'/decision',json={**decision,'decision':'approve'}).status_code==409
        assert c.post(endpoint+'/resume').status_code==409
        next_gate=propose(c,run_id,plan(),'revision').json()['approval_id']
        next_endpoint=f'/api/v1/runs/{run_id}/plan-approvals/{next_gate}'
        revised=c.get(next_endpoint).json()
        assert revised['target_version']==2
        assert c.post(next_endpoint+'/decision',json={'target_id':revised['target_id'],'target_version':2,'decision':'approve','reason':'Revised plan accepted'}).status_code==202
        assert c.get(next_endpoint).json()['baseline_id']
        with Session(app.state.engine) as s:
            assert s.scalar(select(func.count()).select_from(Baseline))==1


def test_gate_replays_committed_baseline_after_checkpoint_gap(tmp_path):
    app=create_app(f'sqlite:///{(tmp_path/"gate-crash.db").as_posix()}')
    with TestClient(app) as c:
        run_id=run(c)
        original=app.state.runtime.save
        def crash(session,state,node,patch):
            result=original(session,state,node,patch)
            if node.startswith('apply_plan_approval:'):
                session.commit()
                raise RuntimeError('Missing checkpoint after commit')
            return result
        app.state.runtime.save=crash
        gate=propose(c,run_id,plan()).json()['approval_id']
        endpoint=f'/api/v1/runs/{run_id}/plan-approvals/{gate}'
        assert c.get(endpoint).json()['baseline_id']
        app.state.runtime.save=original
        assert c.post(endpoint+'/resume').status_code==202
        assert c.get(endpoint).json()['status']=='approve'
        with Session(app.state.engine) as s:
            assert s.scalar(select(func.count()).select_from(Baseline))==1
