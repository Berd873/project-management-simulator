"""Persistent plan/change approval graph. APIs submit commands, nodes commit baselines."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from ..agents.contracts import ApprovalDecision
from ..agents.providers import MockProvider, RealProvider
from ..domain import Role
from ..models import Approval, Artifact, ChangeRequest, NodeReceipt, Project, Run
from ..services.baselines import commit_baseline


class ApprovalState(TypedDict, total=False):
    run_id: str
    project_id: str
    approval_id: str
    artifact_id: str
    change_id: str | None
    effective_day: int
    decision: dict
    result: str
    baseline_id: str | None
    change_spec_id: str


class PlanApprovalWorkflow:
    def __init__(self, runtime, saver):
        self.runtime = runtime
        graph = StateGraph(ApprovalState)
        graph.add_node('sponsor_decision', self.decide)
        graph.add_node('apply_decision', self.apply)
        graph.add_edge(START, 'sponsor_decision')
        graph.add_edge('sponsor_decision', 'apply_decision')
        graph.add_edge('apply_decision', END)
        self.graph = graph.compile(checkpointer=saver)

    @staticmethod
    def config(run_id, approval_id):
        return {'configurable':{'thread_id':f'{run_id}:plan-approval:{approval_id}'}}

    def decide(self, state):
        with self.runtime.sessions() as session:
            approval = session.get(Approval,state['approval_id'])
            artifact = session.get(Artifact,state['artifact_id'])
            project = session.get(Project,state['project_id'])
            human, mode = project.sponsor_mode.value == 'human', project.llm_mode.value
            target = {'target_id':artifact.id,'target_version':artifact.version}
            evidence = {'plan':artifact.payload,'effective_day':state['effective_day'],
                'scheduling_policy':'This is a dependency-only CPM baseline, not a resource-leveled schedule. effective_day is a baseline boundary, NOT the start date of every task. Daily PM dispatch must serialize tasks that share a capacity-1 resource; apparent CPM overlap is handled by that dispatcher and is not by itself an infeasible plan. Review scope, rates, dependencies and stated simulation assumptions; retain independent approve/reject judgment.'}
            if state.get('change_id'):
                change = session.get(ChangeRequest,state['change_id'])
                evidence.update(reason=change.reason,impact=change.impact,source_baseline_id=change.source_baseline_id)
                if state.get('change_spec_id'):
                    evidence['change_spec']=session.get(Artifact,state['change_spec_id']).payload

        def validate(raw):
            decision = ApprovalDecision.model_validate(raw)
            if decision.target_id != target['target_id'] or decision.target_version != target['target_version']:
                raise ValueError('Approval target/version mismatch')
            return decision

        if human:
            decision = validate(interrupt({'approval_id':state['approval_id'],**target,**evidence}))
        else:
            provider = self.runtime.provider or (MockProvider() if mode == 'mock' else RealProvider())
            decision = self.runtime.validated_call(state,f"plan_approval:{state['approval_id']}",Role.SPONSOR,
                provider,{'target':target,'evidence':evidence},lambda:provider.approve(target,evidence),validate)
        return {'decision':decision.model_dump(mode='json')}

    def apply(self, state):
        node = f"apply_plan_approval:{state['approval_id']}"
        cached = self.runtime.receipt(state,node)
        if cached is not None:
            return cached
        with self.runtime.sessions.begin() as session:
            approval = session.get(Approval,state['approval_id'])
            decision = ApprovalDecision.model_validate(state['decision'])
            approval.status, approval.decision = decision.decision, decision.model_dump(mode='json')
            session.flush()
            baseline = None
            if decision.decision == 'approve':
                baseline = commit_baseline(session,state['run_id'],state['artifact_id'],state['approval_id'],
                                            state['effective_day'],state.get('change_id'))
            elif state.get('change_id'):
                session.get(ChangeRequest,state['change_id']).status = 'rejected'
            return self.runtime.save(session,state,node,{'result':decision.decision,
                                                       'baseline_id':baseline.id if baseline else None})

    def drive(self, run_id, approval_id, decision=None):
        config = self.config(run_id,approval_id)
        with self.runtime.sessions() as session:
            row = session.scalar(select(NodeReceipt).where(NodeReceipt.run_id == run_id,
                NodeReceipt.node == f'plan_approval_input:{approval_id}'))
            initial = row.patch
            approval = session.get(Approval,approval_id)
            pending_decision = approval.decision
        snapshot = self.graph.get_state(config)
        # A resume command is needed only while the human decision node is interrupted.
        paused = any(task.interrupts for task in snapshot.tasks)
        value = Command(resume=decision or pending_decision) if paused and (decision or pending_decision) else (None if snapshot.values else initial)
        try:
            self.graph.invoke(value,config)
        except Exception as exc:
            with self.runtime.sessions.begin() as session:
                approval = session.get(Approval,approval_id)
                if approval.status not in ['approve','reject']:
                    approval.status = 'failed'
                self.runtime.emit(session,run_id,'plan_approval_failed',{'approval_id':approval_id,'error':type(exc).__name__})
