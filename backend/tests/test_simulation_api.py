from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Event, SimulationTick


def fixture():
    return json.loads((Path(__file__).resolve().parents[2]/'examples/library_management/scenario.json').read_text())


def proposals(client):
    project = client.post('/api/v1/projects',json={'name':'LMS','description':'Library catalog, readers, loans and search'}).json()['id']
    return client.post(f'/api/v1/projects/{project}/runs',headers={'Idempotency-Key':'lms'}).json()['id']


def test_api_persisted_simulation_and_replay(tmp_path):
    url = f'sqlite:///{(tmp_path/"sim.db").as_posix()}'
    data = fixture()
    request = {key:data[key] for key in ['plan','scenario']}
    app = create_app(url)
    with TestClient(app) as client:
        run = proposals(client)
        endpoint = f'/api/v1/runs/{run}/simulation'
        assert client.post(endpoint,json=request).status_code == 202
        result = client.get(endpoint).json()
        assert result['status'] == 'awaiting_m4'
        assert result['snapshot']['day'] == 7
        assert result['plan_status'] == 'draft_unapproved'
        assert result['metrics'][-1]['ev_cents'] == 30000
        assert result['metrics'][-1]['ac_cents'] == 35000
        assert len(result['ticks']) == 8  # Initial day zero plus seven ticks.
        assert client.post(endpoint,json=request).json()['status'] == 'awaiting_m4'
        changed = deepcopy(request)
        changed['plan']['tasks'][0]['duration_days'] = 4
        assert client.post(endpoint,json=changed).status_code == 409
        assert client.post(endpoint+'/resume').status_code == 409
        stream = client.get(f'/api/v1/runs/{run}/events?follow=false').text
        assert stream.count('event: change_requested\n') == 1
        assert stream.count('event: simulated_test_failed\n') == 1
        with Session(app.state.engine) as session:
            sequences = session.scalars(select(Event.sequence).where(Event.run_id == run).order_by(Event.sequence)).all()
            assert sequences == list(range(1,len(sequences)+1))
            assert session.scalar(select(func.count()).select_from(SimulationTick)) == 8
    with TestClient(create_app(url)) as client:
        assert client.get(endpoint).json() == result
        other = proposals(client)
        client.post(f'/api/v1/runs/{other}/simulation',json=request)
        replay = client.get(f'/api/v1/runs/{other}/simulation').json()
        for key in ['snapshot','metrics','ticks','schedule']:
            assert replay[key] == result[key]


def test_crash_after_tick_commit_resumes_without_double_cost_or_events(tmp_path):
    url = f'sqlite:///{(tmp_path/"crash.db").as_posix()}'
    data = fixture()
    app = create_app(url)
    with TestClient(app) as client:
        driver = app.state.runtime.simulation
        original = driver.persist_tick
        def crash(session,run_id,snapshot,events,metrics,assignments):
            original(session,run_id,snapshot,events,metrics,assignments)
            if snapshot['day'] == 3:
                session.commit()
                raise RuntimeError('Committed tick, missing checkpoint')
        driver.persist_tick = crash
        run = proposals(client)
        endpoint = f'/api/v1/runs/{run}/simulation'
        client.post(endpoint,json={'plan':data['plan'],'scenario':data['scenario']})
        failed = client.get(endpoint).json()
        assert failed['status'] == 'failed'
        assert failed['snapshot']['day'] == 3
    # Reconstruct both checkpoint saver and runtime before retrying.
    with TestClient(create_app(url)) as client:
        assert client.post(endpoint+'/resume').status_code == 202
        recovered = client.get(endpoint).json()
        assert recovered['status'] == 'awaiting_m4'
        assert recovered['metrics'][-1]['ac_cents'] == 35000
        assert len(recovered['ticks']) == 8
        stream = client.get(f'/api/v1/runs/{run}/events?follow=false').text
        assert stream.count('event: change_requested\n') == 1


def test_simulation_api_guardrails(tmp_path):
    data = fixture()
    app = create_app(f'sqlite:///{(tmp_path/"guards.db").as_posix()}')
    with TestClient(app) as client:
        request = {'plan':data['plan'],'scenario':data['scenario']}
        assert client.post('/api/v1/runs/missing/simulation',json=request).status_code == 404
        assert client.get('/api/v1/runs/missing/simulation').status_code == 404
        project = client.post('/api/v1/projects',json={'name':'LMS','description':'Library','sponsor_mode':'human'}).json()['id']
        run = client.post(f'/api/v1/projects/{project}/runs',headers={'Idempotency-Key':'human'}).json()['id']
        endpoint = f'/api/v1/runs/{run}/simulation'
        assert client.post(endpoint,json=request).status_code == 409
        cycle = deepcopy(request)
        cycle['plan']['dependencies'].append({'predecessor':'3','successor':'1'})
        assert client.post(endpoint,json=cycle).status_code == 422
        unknown = deepcopy(request)
        unknown['scenario']['forced_first_test_failures'] = ['missing']
        assert client.post(endpoint,json=unknown).status_code == 422
