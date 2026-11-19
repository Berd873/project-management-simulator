import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import Role
from app.main import create_app
from app.models import Artifact, Project, Task


@pytest.fixture
def app(tmp_path):
    return create_app(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")


def test_create_read_and_restart(tmp_path):
    url = f"sqlite:///{(tmp_path / 'persistent.db').as_posix()}"
    with TestClient(create_app(url)) as client:
        assert client.get('/api/v1/health').json()['status'] == 'ok'
        response = client.post('/api/v1/projects', json={
            'name': 'Library Management System', 'description': 'Borrowing and returns',
        })
        assert response.status_code == 201
        project = response.json()
        assert project['llm_mode'] == 'mock'
        assert project['execution_mode'] == 'simulation'
        assert project['status'] == 'draft'
        assert project['phase'] == 'initiating'
        assert project['simulation_day'] == 0
    with TestClient(create_app(url)) as client:
        assert client.get(f"/api/v1/projects/{project['id']}").json() == project
        assert client.get('/api/v1/projects').json() == [project]
        assert client.get('/api/v1/projects?offset=1').json() == []
        assert client.get('/api/v1/projects/missing').status_code == 404
        assert client.get('/openapi.json').status_code == 200


@pytest.mark.parametrize('patch', [
    {'name': '   '}, {'description': ''}, {'seed': -1}, {'seed': True},
    {'seed': 2.5}, {'seed': 2147483648}, {'llm_mode': 'unknown'},
    {'sponsor_mode': 'unknown'}, {'execution_mode': 'real'}, {'status': 'completed'},
])
def test_reject_invalid_project_without_write(app, patch):
    with TestClient(app) as client:
        payload = {'name': 'LMS', 'description': 'Library management', **patch}
        assert client.post('/api/v1/projects', json=payload).status_code == 422
        assert client.get('/api/v1/projects').json() == []


def test_human_mode_and_pagination(app):
    with TestClient(app) as client:
        response = client.post('/api/v1/projects', json={
            'name': ' LMS ', 'description': 'Library', 'sponsor_mode': 'human', 'seed': 0,
        })
        assert response.json()['name'] == 'LMS'
        assert response.json()['sponsor_mode'] == 'human'
        assert client.get('/api/v1/projects?limit=101').status_code == 422
        assert client.get('/api/v1/projects?offset=-1').status_code == 422


def make_task(project_id, **overrides):
    return Task(**dict(project_id=project_id, wbs_code='1.1', title='Catalog',
                       owner=Role.DEVELOPER, duration_days=2, budget_cents=10000,
                       **overrides))


def test_task_and_artifact_persistence_and_constraints(app):
    with TestClient(app) as client:
        project_id = client.post('/api/v1/projects', json={'name': 'LMS', 'description': 'Library'}).json()['id']
        with Session(app.state.engine) as session:
            session.add(make_task(project_id))
            session.add(Artifact(project_id=project_id, kind='charter', version=1,
                                 author=Role.PROJECT_MANAGER, payload={'objectives': ['Manage library']}))
            session.commit()
        with Session(app.state.engine) as session:
            assert session.scalar(select(Task)).owner == Role.DEVELOPER
            assert session.scalar(select(Artifact)).payload['objectives'] == ['Manage library']
            session.add(make_task(project_id))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            assert session.scalar(select(func.count()).select_from(Task)) == 1
            session.add(Artifact(project_id=project_id, kind='charter', version=1,
                                 author=Role.SPONSOR, payload={}))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            assert session.scalar(select(func.count()).select_from(Artifact)) == 1


@pytest.mark.parametrize('field,value', [('duration_days', 0), ('budget_cents', -1), ('project_id', 'missing')])
def test_task_database_rejects_invalid_rows(app, field, value):
    with TestClient(app) as client:
        project_id = client.post('/api/v1/projects', json={'name': 'LMS', 'description': 'Library'}).json()['id']
        task = make_task(project_id)
        setattr(task, field, value)
        with Session(app.state.engine) as session:
            session.add(task)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            assert session.scalar(select(func.count()).select_from(Task)) == 0
