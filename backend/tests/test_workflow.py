import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.agents.contracts import AgentContext, validate_decision
from app.agents.providers import MockProvider, RealProvider
from app.database import Base, build_engine
from app.domain import Role
from app.main import create_app
from app.models import AgentExecution, Artifact, Event, NodeReceipt, Project


def create(client, mode='llm', llm='mock'):
    return client.post('/api/v1/projects', json={'name': 'LMS', 'description': 'Borrowing and catalog', 'sponsor_mode': mode, 'llm_mode': llm}).json()['id']


def start(client, project, key='demo'):
    return client.post(f'/api/v1/projects/{project}/runs', headers={'Idempotency-Key': key})


def test_six_roles_and_idempotency_and_events(tmp_path):
    app = create_app(f'sqlite:///{(tmp_path / "roles.db").as_posix()}')
    with TestClient(app) as c:
        p = create(c)
        response = start(c, p)
        assert response.status_code == 202
        run = response.json()['id']
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'awaiting_m3'
        traces = c.get(f'/api/v1/runs/{run}/traces').json()
        assert {t['role'] for t in traces} == {r.value for r in Role}
        assert all(t['valid'] for t in traces)
        assert next(t for t in traces if t['role'] == 'tester')['output']['payload']['status'] == 'not_executed'
        assert start(c, p).json()['id'] == run
        assert start(c, p, 'another').status_code == 409
        assert c.post(f'/api/v1/runs/{run}/resume').status_code == 409
        events = c.get(f'/api/v1/runs/{run}/events?follow=false').text
        ids = [int(line[4:]) for line in events.splitlines() if line.startswith('id: ')]
        assert ids == list(range(1, len(ids)+1))
        tail = c.get(f'/api/v1/runs/{run}/events?follow=false', headers={'Last-Event-ID': str(ids[-2])}).text
        assert tail.count('id: ') == 1
        assert 'simulation' in tail


@pytest.mark.parametrize('outcome,expected', [('approve','awaiting_m3'), ('reject','rejected')])
def test_human_restart_and_version_binding(tmp_path, outcome, expected):
    url = f'sqlite:///{(tmp_path / "human.db").as_posix()}'
    with TestClient(create_app(url)) as c:
        p = create(c, 'human')
        run = start(c, p).json()['id']
        status = c.get(f'/api/v1/runs/{run}').json()
        assert status['status'] == 'waiting_approval'
        approval = status['approvals'][0]
        assert len(c.get(f'/api/v1/runs/{run}/traces').json()) == 2
    with TestClient(create_app(url)) as c:
        endpoint = f"/api/v1/runs/{run}/approvals/{approval['id']}"
        decision = {k: approval[k] for k in ['target_id','target_version']}
        decision.update(decision=outcome, reason='Reviewed charter')
        assert c.post(endpoint, json={**decision, 'target_version': 999}).status_code == 409
        assert c.post(endpoint, json=decision).status_code == 202
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == expected
        assert c.post(endpoint, json=decision).status_code == 202
        assert c.post(endpoint, json={**decision, 'reason':'Different intent'}).status_code == 409
        assert len(c.get(f'/api/v1/runs/{run}/traces').json()) == (6 if outcome == 'approve' else 2)


class InvalidProvider(MockProvider):
    def generate(self, context):
        return {'role':'developer','payload': {'secret':'do-not-persist'}}


def test_invalid_output_bounded_retries_and_no_secret_leak(tmp_path):
    app = create_app(f'sqlite:///{(tmp_path / "invalid.db").as_posix()}', provider=InvalidProvider())
    with TestClient(app) as c:
        run = start(c, create(c)).json()['id']
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'failed'
        traces = c.get(f'/api/v1/runs/{run}/traces').json()
        assert len(traces) == 3
        assert not any(t['valid'] for t in traces)
        assert 'do-not-persist' not in json.dumps(traces)
        assert c.post(f'/api/v1/runs/{run}/resume').status_code == 202
        assert len(c.get(f'/api/v1/runs/{run}/traces').json()) == 3


def test_business_rule_guards():
    context = AgentContext(project_id='p', run_id='r', role=Role.DEVELOPER, brief='LMS')
    raw = {'role':'developer','rationale':'proposal', 'payload': {'task_ids':['unknown'],'approach':'x'}}
    with pytest.raises(ValueError, match='Unknown task'):
        validate_decision(raw, context)
    with pytest.raises(ValueError, match='Role mismatch'):
        validate_decision({**raw, 'role':'tester'}, context)


def test_replay_after_business_commit_before_checkpoint(tmp_path):
    app = create_app(f'sqlite:///{(tmp_path / "crash.db").as_posix()}')
    with TestClient(app) as c:
        runtime = app.state.runtime
        original = runtime.save
        crashed = False
        def crash_save(session, state, node, patch):
            nonlocal crashed
            result = original(session, state, node, patch)
            if node == 'requirements_analyst' and not crashed:
                session.commit()  # Exact crash window: business receipt durable, checkpoint absent.
                crashed = True
                raise RuntimeError('Injected crash')
            return result
        runtime.save = crash_save
        run = start(c, create(c)).json()['id']
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'failed'
        runtime.save = original
        assert c.post(f'/api/v1/runs/{run}/resume').status_code == 202
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'awaiting_m3'
        with Session(app.state.engine) as s:
            assert s.scalar(select(func.count()).select_from(Artifact)) == 6
            assert s.scalar(select(func.count()).select_from(AgentExecution)) == 7
            assert s.scalar(select(func.count()).select_from(NodeReceipt).where(NodeReceipt.node == 'requirements_analyst')) == 1


def test_upgrade_existing_m1_preserves_data(tmp_path):
    url = f'sqlite:///{(tmp_path / "old.db").as_posix()}'
    engine = build_engine(url)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[n] for n in ['projects','tasks','artifacts']])
    with Session(engine) as s:
        project = Project(name='Existing LMS', description='Preserve me')
        s.add(project)
        s.commit()
        project_id = project.id
    engine.dispose()
    with TestClient(create_app(url)) as c:
        assert c.get(f'/api/v1/projects/{project_id}').json()['name'] == 'Existing LMS'
        assert start(c, project_id).status_code == 202


def test_real_provider_requires_config_and_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    with pytest.raises(ValueError):
        RealProvider()
    with TestClient(create_app(f'sqlite:///{(tmp_path / "real.db").as_posix()}')) as c:
        run = start(c, create(c, llm='real')).json()['id']
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'failed'
        assert c.get(f'/api/v1/runs/{run}/traces').json() == []


def test_real_http_adapter_and_sponsor_approval(monkeypatch):
    import httpx
    monkeypatch.setenv('LLM_API_KEY', 'private-test-key')
    monkeypatch.setenv('LLM_MODEL', 'test-model')
    monkeypatch.setenv('LLM_BASE_URL', 'https://model.invalid/v1')
    context = AgentContext(project_id='p', run_id='r', role=Role.SPONSOR, brief='LMS')
    target = {'target_id': 'charter-id', 'target_version': 1}
    replies = [MockProvider().generate(context), {**target, 'decision':'reject', 'reason':'Budget unclear'}]
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(replies.pop(0))}}]})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    provider = RealProvider()
    assert validate_decision(provider.generate(context), context).role == Role.SPONSOR
    assert provider.approve(target, {'objectives':['LMS']})['decision'] == 'reject'
    assert len(requests) == 2
    assert str(requests[0].url) == 'https://model.invalid/v1/chat/completions'
    assert requests[0].headers['Authorization'] == 'Bearer private-test-key'


def test_restart_after_approval_intent_before_graph_resume(tmp_path):
    from app.models import Approval, Run
    url = f'sqlite:///{(tmp_path / "intent.db").as_posix()}'
    app = create_app(url)
    with TestClient(app) as c:
        run = start(c, create(c, 'human')).json()['id']
        with Session(app.state.engine) as s:
            approval = s.scalar(select(Approval).where(Approval.run_id == run))
            approval.decision = {'target_id': approval.target_id, 'target_version':approval.target_version,
                                 'decision':'approve','reason':'Persisted before process stopped'}
            s.get(Run, run).status = 'ready'
            s.commit()
    with TestClient(create_app(url)) as c:
        assert c.post(f'/api/v1/runs/{run}/resume').status_code == 202
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'awaiting_m3'


def test_sponsor_approval_is_validated_bounded_and_audited(tmp_path):
    class BadApproval(MockProvider):
        def approve(self, target, charter):
            return {**target, 'target_version': 999, 'decision':'approve', 'reason':'wrong version'}
    app = create_app(f'sqlite:///{(tmp_path / "bad-approval.db").as_posix()}', provider=BadApproval())
    with TestClient(app) as c:
        run = start(c, create(c)).json()['id']
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'failed'
        attempts = [t for t in c.get(f'/api/v1/runs/{run}/traces').json() if t['node'] == 'sponsor_approval']
        assert len(attempts) == 3
        assert all(not t['valid'] and t['error'] == 'Conflict' for t in attempts)
        assert c.get(f'/api/v1/runs/{run}').json()['approvals'][0]['status'] == 'pending'
        c.post(f'/api/v1/runs/{run}/resume')
        assert len(c.get(f'/api/v1/runs/{run}/traces').json()) == 5


def test_sponsor_decision_reused_after_business_commit_crash(tmp_path):
    class CountingProvider(MockProvider):
        calls = 0
        def approve(self, target, charter):
            self.calls += 1
            return super().approve(target, charter)
    provider = CountingProvider()
    app = create_app(f'sqlite:///{(tmp_path / "approval-crash.db").as_posix()}', provider=provider)
    with TestClient(app) as c:
        original = app.state.runtime.save
        def crash_save(session, state, node, patch):
            if node == 'approve':
                raise RuntimeError('Crash after decision audit before business commit')
            return original(session, state, node, patch)
        app.state.runtime.save = crash_save
        run = start(c, create(c)).json()['id']
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'failed'
        assert provider.calls == 1
        app.state.runtime.save = original
        c.post(f'/api/v1/runs/{run}/resume')
        assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'awaiting_m3'
        assert provider.calls == 1


def test_checkpoint_survives_separate_python_processes(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    url = f'sqlite:///{(tmp_path / "process.db").as_posix()}'
    common = '''
import json, sys
from fastapi.testclient import TestClient
from app.main import create_app
'''
    first = common + '''
with TestClient(create_app(sys.argv[1])) as c:
    p = c.post('/api/v1/projects', json={'name':'LMS','description':'Borrowing','sponsor_mode':'human'}).json()['id']
    run = c.post(f'/api/v1/projects/{p}/runs', headers={'Idempotency-Key':'restart'}).json()['id']
    status = c.get(f'/api/v1/runs/{run}').json()
    assert status['status'] == 'waiting_approval'
    print(json.dumps(status))
'''
    second = common + '''
status = json.loads(sys.argv[2])
with TestClient(create_app(sys.argv[1])) as c:
    a = status['approvals'][0]
    run = status['id']
    response = c.post(f"/api/v1/runs/{run}/approvals/{a['id']}", json={'target_id':a['target_id'],'target_version':a['target_version'],'decision':'approve','reason':'Approved in another process'})
    assert response.status_code == 202, response.text
    assert c.get(f'/api/v1/runs/{run}').json()['status'] == 'awaiting_m3'
    assert len(c.get(f'/api/v1/runs/{run}/traces').json()) == 6
'''
    # Use separate OS processes, not just reconstructed app objects; isolate import-time default DB.
    env = {**os.environ, 'DATABASE_URL':url}
    before = subprocess.run([sys.executable,'-c',first,url], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert before.returncode == 0, before.stderr
    after = subprocess.run([sys.executable,'-c',second,url,before.stdout.strip()], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert after.returncode == 0, after.stderr
