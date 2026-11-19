from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func,select,text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import Role
from app.main import create_app
from app.models import Approval,Artifact,Baseline,ChangeRequest,Project,Run
from app.services.baselines import BaselineConflict,active_baseline,analyze_change,commit_baseline,propose_change
from app.services.planning import Plan


@pytest.fixture
def context(tmp_path):
    app=create_app(f'sqlite:///{(tmp_path/"baselines.db").as_posix()}')
    with TestClient(app):
        with Session(app.state.engine,expire_on_commit=False) as session:
            project=Project(name='LMS',description='Library')
            session.add(project)
            session.flush()
            run=Run(project_id=project.id,request_key='baseline')
            session.add(run)
            session.commit()
            data=json.loads((Path(__file__).resolve().parents[2]/'examples/library_management/scenario.json').read_text())
            yield session,run,data['plan']


def artifact_approval(session,run,plan,status='approve',artifact_version=None):
    artifact=Artifact(project_id=run.project_id,kind='plan',version=artifact_version or plan['version'],author=Role.PROGRESS_COST_ANALYST,payload=plan)
    session.add(artifact)
    session.flush()
    approval=Approval(run_id=run.id,target_id=artifact.id,target_version=artifact.version,status=status,
        decision={'target_id':artifact.id,'target_version':artifact.version,'decision':status,'reason':'Reviewed plan'} if status in ['approve','reject'] else None)
    session.add(approval)
    session.flush()
    return artifact,approval


def initial(session,run,plan):
    artifact,approval=artifact_approval(session,run,plan)
    baseline=commit_baseline(session,run.id,artifact.id,approval.id)
    session.commit()
    return baseline


def changed(plan):
    result=deepcopy(plan)
    result['version']=2
    result['tasks'].append({'id':'5','title':'Overdue reminders','duration_days':2,'budget_cents':10000,'resource_id':'developer'})
    result['dependencies'].append({'predecessor':'3','successor':'5'})
    return result


def test_initial_approval_version_binding_and_idempotency(context):
    session,run,plan=context
    artifact,approval=artifact_approval(session,run,plan,'pending')
    with pytest.raises(ValueError):
        commit_baseline(session,run.id,artifact.id,approval.id)
    approval.status='approve'
    approval.decision={'target_id':artifact.id,'target_version':99,'decision':'approve','reason':'stale'}
    session.flush()
    with pytest.raises(BaselineConflict,match='version'):
        commit_baseline(session,run.id,artifact.id,approval.id)
    approval.decision={**approval.decision,'target_version':1}
    session.flush()
    baseline=commit_baseline(session,run.id,artifact.id,approval.id)
    session.commit()
    assert baseline.version==1 and baseline.previous_id is None
    assert len(baseline.content_hash)==64
    assert commit_baseline(session,run.id,artifact.id,approval.id).id==baseline.id
    assert session.scalar(select(func.count()).select_from(Baseline))==1


def test_revised_artifact_after_rejection_can_become_first_baseline(context):
    session,run,plan=context
    _,rejected=artifact_approval(session,run,plan,'reject')
    session.commit()
    revised,approval=artifact_approval(session,run,plan,artifact_version=2)
    baseline=commit_baseline(session,run.id,revised.id,approval.id)
    session.commit()
    assert baseline.version==1
    assert session.get(Artifact,baseline.artifact_id).version==2
    assert session.get(Approval,rejected.id).status=='reject'


def test_complete_approved_change_keeps_history_and_source_guard(context):
    session,run,plan=context
    old=initial(session,run,plan)
    old_hash=old.content_hash
    artifact,approval=artifact_approval(session,run,changed(plan))
    change=propose_change(session,run.id,old.id,artifact.id,'change-1','Add reminders',{'1'})
    session.commit()  # Force JSON roundtrip before applying persisted impact analysis.
    session.expire_all()
    assert change.impact['delta_bac_cents']==10000
    assert change.impact['delta_duration_days']==2
    assert propose_change(session,run.id,old.id,artifact.id,'change-1','Add reminders',{'1'}).id==change.id
    new=commit_baseline(session,run.id,artifact.id,approval.id,effective_day=3,change_id=change.id)
    session.commit()
    assert new.previous_id==old.id and new.version==2
    assert active_baseline(session,run.project_id).id==new.id
    assert session.get(Baseline,old.id).content_hash==old_hash
    assert session.get(Baseline,old.id).content['plan']==Plan.model_validate(plan).model_dump(mode='json')
    assert change.status=='applied' and change.applied_baseline_id==new.id
    assert commit_baseline(session,run.id,artifact.id,approval.id,3,change.id).id==new.id
    with pytest.raises(BaselineConflict,match='stale'):
        propose_change(session,run.id,old.id,artifact.id,'stale','stale source',set())


def test_cannot_bypass_formal_change_or_rejected_approval(context):
    session,run,plan=context
    old=initial(session,run,plan)
    artifact,approval=artifact_approval(session,run,changed(plan),'reject')
    change=propose_change(session,run.id,old.id,artifact.id,'reject','Rejected reminder',set())
    with pytest.raises(BaselineConflict,match='approval'):
        commit_baseline(session,run.id,artifact.id,approval.id,3,change.id)
    approval.status='approve'
    approval.decision={**approval.decision,'decision':'approve'}
    session.flush()
    with pytest.raises(BaselineConflict,match='formal change'):
        commit_baseline(session,run.id,artifact.id,approval.id,3)
    assert active_baseline(session,run.project_id).id==old.id


@pytest.mark.parametrize('mutation',['remove','budget','dependency'])
def test_accepted_work_cannot_be_rewritten(context,mutation):
    _,_,plan=context
    candidate=changed(plan)
    if mutation=='remove':
        candidate['tasks']=[t for t in candidate['tasks'] if t['id']!='4']
        candidate['dependencies']=[e for e in candidate['dependencies'] if e['successor']!='4']
    elif mutation=='budget':
        candidate['tasks'][3]['budget_cents']=1
    else:
        candidate['dependencies']=[e for e in candidate['dependencies'] if e['successor']!='4']
    with pytest.raises(BaselineConflict,match='Accepted task'):
        analyze_change(Plan.model_validate(plan),Plan.model_validate(candidate),{'4'})


@pytest.mark.parametrize('statement',[
    "UPDATE baselines SET content_hash='tampered'",
    "DELETE FROM baselines",
    "UPDATE artifacts SET payload='{}' WHERE kind='plan'",
    "UPDATE approvals SET status='reject'",
])
def test_database_rejects_overwriting_approved_history(context,statement):
    session,run,plan=context
    baseline=initial(session,run,plan)
    baseline_id=baseline.id
    with pytest.raises(IntegrityError):
        session.execute(text(statement))
        session.commit()
    session.rollback()
    assert session.get(Baseline,baseline_id).version==1
