from langgraph.types import interrupt
from sqlalchemy import func,select
from ..agents.contracts import ApprovalDecision
from ..agents.providers import MockProvider,RealProvider
from ..domain import Phase,ProjectStatus,Role
from ..models import Approval,Artifact,Project,Run
from ..services.reports import closure_evidence
from .execution_agents import call_role


def prepare(workflow,state):
    runtime=workflow.runtime
    cached=runtime.receipt(state,'prepare_closure')
    if cached is not None:
        return cached
    with runtime.sessions() as session:
        report=closure_evidence(session,state['run_id'])
    recommendation=call_role(runtime,state['run_id'],state['snapshot']['day'],Role.PROJECT_MANAGER,'close',report)
    report['pm_recommendation']=recommendation.payload
    with runtime.sessions.begin() as session:
        version=(session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==report['project_id'],Artifact.kind=='closure_candidate')) or 0)+1
        artifact=Artifact(project_id=report['project_id'],kind='closure_candidate',version=version,author=Role.PROJECT_MANAGER,payload=report)
        session.add(artifact)
        session.flush()
        approval=Approval(run_id=state['run_id'],target_id=artifact.id,target_version=version)
        session.add(approval)
        session.flush()
        project=session.get(Project,report['project_id'])
        project.phase,project.status=Phase.CLOSING,ProjectStatus.WAITING_APPROVAL
        return runtime.save(session,state,'prepare_closure',{'closure_approval_id':approval.id,'closure_artifact_id':artifact.id})


def review(workflow,state):
    runtime=workflow.runtime
    with runtime.sessions() as session:
        approval=session.get(Approval,state['closure_approval_id'])
        artifact=session.get(Artifact,state['closure_artifact_id'])
        project=session.get(Project,artifact.project_id)
        human,mode=project.sponsor_mode.value=='human',project.llm_mode.value
        target={'target_id':artifact.id,'target_version':artifact.version}
        report=artifact.payload
    def validate(raw):
        decision=ApprovalDecision.model_validate(raw)
        if decision.target_id!=target['target_id'] or decision.target_version!=target['target_version']:
            raise ValueError('Final acceptance target/version mismatch')
        return decision
    if human:
        interrupt({'kind':'final_acceptance','approval_id':state['closure_approval_id'],**target})
        with runtime.sessions() as session:
            decision=validate(session.get(Approval,state['closure_approval_id']).decision)
    else:
        provider=runtime.provider or (MockProvider() if mode=='mock' else RealProvider())
        decision=runtime.validated_call(state,'final_acceptance',Role.SPONSOR,provider,{'target':target,'report':report},
            lambda:provider.approve(target,report),validate)
    return {'closure_decision':decision.model_dump(mode='json')}


def archive(workflow,state):
    runtime=workflow.runtime
    cached=runtime.receipt(state,'archive_closure')
    if cached is not None:
        return cached
    with runtime.sessions.begin() as session:
        # Recheck deterministic guards immediately before marking the project completed.
        closure_evidence(session,state['run_id'])
        approval=session.get(Approval,state['closure_approval_id'])
        decision=ApprovalDecision.model_validate(state['closure_decision'])
        approval.status,approval.decision=decision.decision,decision.model_dump(mode='json')
        candidate=session.get(Artifact,state['closure_artifact_id'])
        report_id=None
        if decision.decision=='approve':
            version=(session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==candidate.project_id,Artifact.kind=='project_report')) or 0)+1
            report=Artifact(project_id=candidate.project_id,kind='project_report',version=version,author=Role.PROJECT_MANAGER,
                            payload={**candidate.payload,'sponsor_acceptance':decision.model_dump(mode='json')})
            session.add(report)
            session.flush()
            report_id=report.id
            session.get(Project,candidate.project_id).status=ProjectStatus.COMPLETED
            session.get(Run,state['run_id']).status='completed'
        return runtime.save(session,state,'archive_closure',{'closure_result':decision.decision,'report_id':report_id})
