from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.planning import Plan
from app.services.rebaseline import metrics,transition
from app.services.simulation import initial_snapshot,step,Scenario


def fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'examples/library_management/scenario.json').read_text())


def setup(c,human=False):
    data=fixture()
    project=c.post('/api/v1/projects',json={'name':'LMS','description':'Catalog, readers, borrowing and search',
        'sponsor_mode':'human' if human else 'llm'}).json()['id']
    run=c.post(f'/api/v1/projects/{project}/runs',headers={'Idempotency-Key':'setup'}).json()['id']
    if human:
        approval=c.get(f'/api/v1/runs/{run}').json()['approvals'][0]
        c.post(f"/api/v1/runs/{run}/approvals/{approval['id']}",json={
            'target_id':approval['target_id'],'target_version':approval['target_version'],'decision':'approve','reason':'Charter accepted'})
    gate=c.post(f'/api/v1/runs/{run}/plan-approvals',headers={'Idempotency-Key':'initial'},json={'plan':data['plan']}).json()['approval_id']
    if human:
        decide(c,run,gate,'approve')
    data['scenario']['formal_management']=True
    response=c.post(f'/api/v1/runs/{run}/simulation',json={'plan':data['plan'],'scenario':data['scenario']})
    assert response.status_code==202,response.text
    return run


def decide(c,run,gate,result):
    endpoint=f'/api/v1/runs/{run}/plan-approvals/{gate}'
    approval=c.get(endpoint).json()
    response=c.post(endpoint+'/decision',json={'target_id':approval['target_id'],'target_version':approval['target_version'],
        'decision':result,'reason':'Review completed'})
    assert response.status_code==202,response.text


def test_automatic_change_preserves_history_and_finishes_new_scope(tmp_path):
    with TestClient(create_app(f'sqlite:///{(tmp_path/"auto.db").as_posix()}')) as c:
        run=setup(c)
        result=c.get(f'/api/v1/runs/{run}/simulation').json()
        assert result['status']=='awaiting_m4',result
        assert result['plan_status']=='approved'
        assert result['snapshot']['day']==9
        assert result['snapshot']['plan_version']==2
        assert len(result['snapshot']['tasks'])==5
        assert all(p['accepted_day'] is not None for p in result['snapshot']['tasks'].values())
        assert [m['baseline_version'] for m in result['metrics'][:4]]==[1]*4
        assert all(m['baseline_version']==2 for m in result['metrics'][4:])
        assert result['metrics'][3]['pv_cents']==25000
        assert result['metrics'][4]['pv_cents']>=25000
        assert result['metrics'][-1]['ev_cents']==40000
        assert result['metrics'][-1]['ac_cents']==45000
        baselines=c.get(f'/api/v1/runs/{run}/baselines').json()
        assert len(baselines)==2 and baselines[1]['effective_day']==3
        reviewed=baselines[1]['content']['execution_transition']
        assert reviewed['pv_anchor']==result['snapshot']['pv_anchor']
        assert reviewed['remaining_forecast']==result['snapshot']['remaining_forecast']
        assert reviewed['source_day']==3
        assert len(reviewed['source_snapshot_hash'])==64
        assert c.get(f'/api/v1/runs/{run}/changes').json()[0]['status']=='applied'


@pytest.mark.parametrize('outcome,days,versions',[('approve',9,2),('reject',7,1)])
def test_human_change_pause_restart_and_resume(tmp_path,outcome,days,versions):
    url=f'sqlite:///{(tmp_path/"human.db").as_posix()}'
    with TestClient(create_app(url)) as c:
        run=setup(c,True)
        before=c.get(f'/api/v1/runs/{run}/simulation').json()
        assert before['status']=='waiting_change',before
        assert before['snapshot']['day']==3
        gate=next(a['id'] for a in c.get(f'/api/v1/runs/{run}').json()['approvals'] if a['status']=='pending')
        assert c.post(f'/api/v1/runs/{run}/simulation/resume').status_code==409
    with TestClient(create_app(url)) as c:
        decide(c,run,gate,outcome)
        response=c.post(f'/api/v1/runs/{run}/simulation/resume')
        assert response.status_code==202,response.text
        after=c.get(f'/api/v1/runs/{run}/simulation').json()
        assert after['status']=='awaiting_m4',after
        assert after['snapshot']['day']==days
        assert after['metrics'][:4]==before['metrics']
        assert len(c.get(f'/api/v1/runs/{run}/baselines').json())==versions
        assert c.get(f'/api/v1/runs/{run}/changes').json()[0]['status']==('applied' if outcome=='approve' else 'rejected')


def test_transition_preserves_started_work_and_pv_anchor():
    data=fixture()
    old=Plan.model_validate(data['plan'])
    snapshot,_,_=step(old,initial_snapshot(old,42),Scenario(),['1'])
    candidate=deepcopy(data['plan'])
    candidate['version']=2
    candidate['tasks'].append({'id':'5','title':'Reminders','duration_days':1,'budget_cents':5000,'resource_id':'developer'})
    proposed=Plan.model_validate(candidate)
    pv=metrics(old,snapshot)['pv_cents']
    migrated=transition(old,proposed,snapshot,pv)
    assert snapshot['plan_version']==1
    assert migrated['tasks']['1']==snapshot['tasks']['1']
    assert migrated['rng_state']==snapshot['rng_state']
    assert metrics(proposed,migrated)['pv_cents']==pv
    candidate['tasks'][0]['duration_days']=3
    with pytest.raises(ValueError,match='Started work'):
        transition(old,Plan.model_validate(candidate),snapshot,pv)


def test_committed_change_transition_replays_without_duplicate_work(tmp_path):
    app=create_app(f'sqlite:///{(tmp_path/"transition-crash.db").as_posix()}')
    with TestClient(app) as c:
        original=app.state.runtime.save
        def crash(session,state,node,patch):
            result=original(session,state,node,patch)
            if node=='review_simulation_change':
                session.commit()
                raise RuntimeError('Transition committed before checkpoint')
            return result
        app.state.runtime.save=crash
        run=setup(c)
        endpoint=f'/api/v1/runs/{run}/simulation'
        failed=c.get(endpoint).json()
        assert failed['status']=='failed'
        assert failed['snapshot']['day']==3
        assert len(c.get(f'/api/v1/runs/{run}/baselines').json())==2

        app.state.runtime.save=original
        response=c.post(endpoint+'/resume')
        assert response.status_code==202,response.text
        result=c.get(endpoint).json()
        assert result['status']=='awaiting_m4',result
        assert result['snapshot']['day']==9
        assert result['metrics'][-1]['ac_cents']==45000
        assert len(c.get(f'/api/v1/runs/{run}/changes').json())==1
        assert len(c.get(f'/api/v1/runs/{run}/baselines').json())==2


def test_change_commit_rechecks_reviewed_source_snapshot(tmp_path):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.models import SimulationTick
    app=create_app(f'sqlite:///{(tmp_path/"changed-source.db").as_posix()}')
    with TestClient(app) as c:
        run=setup(c,True)
        pending=next(a for a in c.get(f'/api/v1/runs/{run}').json()['approvals'] if a['status']=='pending')
        gate=pending['id']
        impact=c.get(f'/api/v1/runs/{run}/plan-approvals/{gate}').json()['impact']
        assert impact['execution_transition']['source_day']==3
        with Session(app.state.engine) as session:
            tick=session.scalar(select(SimulationTick).where(SimulationTick.run_id==run,SimulationTick.day==3))
            changed=deepcopy(tick.snapshot)
            changed['tasks']['1']['actual_cost_cents']+=1
            tick.snapshot=changed
            session.commit()
        decide(c,run,gate,'approve')
        assert c.get(f'/api/v1/runs/{run}/plan-approvals/{gate}').json()['status']=='failed'
        assert len(c.get(f'/api/v1/runs/{run}/baselines').json())==1
