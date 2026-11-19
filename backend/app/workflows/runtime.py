import hashlib
import json
import sqlite3
import threading
import time
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import func, select

from ..agents.contracts import AgentContext, ApprovalDecision, validate_decision
from ..agents.providers import MockProvider, RealProvider
from ..domain import Role
from ..models import AgentExecution, Approval, Artifact, Event, NodeReceipt, Project, Run


class ProjectState(TypedDict, total=False):
    project_id: str
    run_id: str
    artifact_refs: dict[str, str]
    approval_id: str
    approved: bool
    stage: str


class Conflict(ValueError):
    pass


class Runtime:
    def __init__(self, sessions, checkpoint_path, provider=None):
        self.sessions = sessions
        self.provider = provider
        self.lock = threading.Lock()  # Local laboratory: serialize mutating graph commands.
        self.connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
        saver = SqliteSaver(self.connection)
        self.graph = self.build_graph(saver)
        from .simulation import SimulationWorkflow
        self.simulation = SimulationWorkflow(self, saver)
        from .plan_approval import PlanApprovalWorkflow
        self.plan_approval = PlanApprovalWorkflow(self, saver)
        from .delivery import DeliveryWorkflow
        self.delivery = DeliveryWorkflow(self, saver)

    def close(self):
        self.connection.close()

    @staticmethod
    def config(run_id):
        return {"configurable": {"thread_id": run_id}}

    def emit(self, session, run_id, kind, payload):
        sequence = (session.scalar(select(func.max(Event.sequence)).where(Event.run_id == run_id)) or 0) + 1
        session.add(Event(run_id=run_id, sequence=sequence, kind=kind,
                          payload={"execution_mode": "simulation", **payload}))

    def receipt(self, state, node):
        with self.sessions() as s:
            return s.scalar(select(NodeReceipt.patch).where(NodeReceipt.run_id == state['run_id'], NodeReceipt.node == node))

    def save(self, session, state, node, patch):
        session.add(NodeReceipt(run_id=state['run_id'], node=node, patch=patch))
        self.emit(session, state['run_id'], node, patch)
        return patch

    def agent_node(self, role):
        def execute(state):
            node = role.value
            cached = self.receipt(state, node)
            if cached is not None:
                return cached
            with self.sessions() as s:
                project = s.get(Project, state['project_id'])
                brief, mode = project.description, project.llm_mode.value
                artifacts = {name: s.get(Artifact, ref).payload for name, ref in state.get('artifact_refs', {}).items() if not name.startswith('task:')}
            context = AgentContext(project_id=state['project_id'], run_id=state['run_id'], role=role,
                                   brief=brief, artifact_refs=state.get('artifact_refs', {}), artifacts=artifacts)
            provider = self.provider or (MockProvider() if mode == 'mock' else RealProvider())
            decision = self.validated_call(
                state, node, role, provider, context.model_dump(mode='json'),
                lambda: provider.generate(context), lambda raw: validate_decision(raw, context))
            with self.sessions.begin() as s:
                if role == Role.REQUIREMENTS_ANALYST:
                    from ..domain import Phase
                    s.get(Project,state['project_id']).phase=Phase.PLANNING
                version = (s.scalar(select(func.max(Artifact.version)).where(Artifact.project_id == state['project_id'], Artifact.kind == node)) or 0) + 1
                artifact = Artifact(project_id=state['project_id'], kind=node, version=version, author=role, payload=decision.payload)
                s.add(artifact)
                s.flush()
                refs = {**state.get('artifact_refs', {}), node: artifact.id}
                if role == Role.REQUIREMENTS_ANALYST:
                    refs.update({f"task:{t['id']}": artifact.id for t in decision.payload['tasks']})
                return self.save(s, state, node, {"artifact_refs": refs})
        return execute

    def validated_call(self, state, node, role, provider, inputs, generate, validate):
        """Persist a successful decision before its business effects, replay without recalling LLM."""
        input_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        for attempt in range(1, 4):
            with self.sessions() as s:
                existing = s.scalar(select(AgentExecution).where(
                    AgentExecution.run_id == state['run_id'], AgentExecution.node == node,
                    AgentExecution.attempt == attempt))
                if existing:
                    if existing.input_hash != input_hash:
                        raise Conflict('Decision input changed during replay')
                    if existing.valid:
                        return validate(existing.output)
                    continue
            started = time.monotonic()
            decision, error = None, None
            try:
                decision = validate(generate())
            except Exception as exc:
                error = type(exc).__name__  # Never persist provider exception bodies or invalid raw output.
            with self.sessions.begin() as s:
                s.add(AgentExecution(run_id=state['run_id'], node=node, role=role.value,
                    attempt=attempt, provider=provider.name, prompt_version=getattr(provider,'prompt_version','custom-v1'), input_hash=input_hash,
                    output=decision.model_dump(mode='json') if decision else {},
                    valid=decision is not None, elapsed_ms=int((time.monotonic()-started)*1000), error=error))
            if decision is not None:
                return decision
        raise ValueError('Agent decision failed validation after three attempts')

    def prepare_approval(self, state):
        cached = self.receipt(state, 'prepare_approval')
        if cached is not None:
            return cached
        with self.sessions.begin() as s:
            target = s.get(Artifact, state['artifact_refs'][Role.PROJECT_MANAGER.value])
            approval = Approval(run_id=state['run_id'], target_id=target.id, target_version=target.version)
            s.add(approval)
            s.flush()
            return self.save(s, state, 'prepare_approval', {'approval_id': approval.id})

    def approve(self, state):
        cached = self.receipt(state, 'approve')
        if cached is not None:
            return cached
        with self.sessions() as s:
            approval = s.get(Approval, state['approval_id'])
            target = {'target_id': approval.target_id, 'target_version': approval.target_version}
            human = s.get(Project, state['project_id']).sponsor_mode.value == 'human'
            mode = s.get(Project, state['project_id']).llm_mode.value
            charter = s.get(Artifact, approval.target_id).payload
        # No side effects before interrupt; preparing the approval is a separate node.
        def validate(raw):
            decision = ApprovalDecision.model_validate(raw)
            if decision.target_id != target['target_id'] or decision.target_version != target['target_version']:
                raise Conflict('Stale approval target')
            return decision

        if human:
            decision = validate(interrupt({'approval_id': state['approval_id'], **target}))
        else:
            provider = self.provider or (MockProvider() if mode == 'mock' else RealProvider())
            decision = self.validated_call(state, 'sponsor_approval', Role.SPONSOR, provider,
                {'target': target, 'charter': charter}, lambda: provider.approve(target, charter), validate)
        with self.sessions.begin() as s:
            approval = s.get(Approval, state['approval_id'])
            approval.decision = decision.model_dump()
            approval.status = decision.decision
            return self.save(s, state, 'approve', {'approved': decision.decision == 'approve'})

    def finish(self, state):
        cached = self.receipt(state, 'finish')
        if cached is not None:
            return cached
        with self.sessions.begin() as s:
            return self.save(s, state, 'finish', {'stage': 'awaiting_m3' if state['approved'] else 'charter_rejected'})

    def build_graph(self, saver):
        graph = StateGraph(ProjectState)
        for role in Role:
            graph.add_node(role.value, self.agent_node(role))
        graph.add_node('prepare_approval', self.prepare_approval)
        graph.add_node('approve', self.approve)
        graph.add_node('finish', self.finish)
        graph.add_edge(START, 'sponsor')
        graph.add_edge('sponsor', 'project_manager')
        graph.add_edge('project_manager', 'prepare_approval')
        graph.add_edge('prepare_approval', 'approve')
        graph.add_conditional_edges('approve', lambda s: 'requirements_analyst' if s['approved'] else 'finish')
        graph.add_edge('requirements_analyst', 'progress_cost_analyst')
        graph.add_edge('progress_cost_analyst', 'developer')
        graph.add_edge('developer', 'tester')
        graph.add_edge('tester', 'finish')
        graph.add_edge('finish', END)
        return graph.compile(checkpointer=saver)

    def drive(self, run_id, decision=None):
        with self.sessions() as s:
            run = s.get(Run, run_id)
            snapshot = self.graph.get_state(self.config(run_id))
            if not decision and snapshot.next and snapshot.values.get('approval_id'):
                pending = s.get(Approval, snapshot.values['approval_id'])
                if pending and pending.decision:
                    decision = pending.decision
            value = Command(resume=decision) if decision else (None if snapshot.values else {'project_id': run.project_id, 'run_id': run_id, 'artifact_refs': {}})
        try:
            self.graph.invoke(value, self.config(run_id))
            snapshot = self.graph.get_state(self.config(run_id))
            status = 'waiting_approval' if snapshot.next else ('awaiting_m3' if snapshot.values.get('approved') else 'rejected')
            with self.sessions.begin() as s:
                s.get(Run, run_id).status = status
                s.get(Run, run_id).error = None
        except Exception as exc:
            with self.sessions.begin() as s:
                s.get(Run, run_id).status = 'failed'
                s.get(Run, run_id).error = type(exc).__name__
