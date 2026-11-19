"""Persistent LangGraph driver for deterministic M3 simulation services."""
import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy import select

from ..models import Baseline,Run,SimulationRun,SimulationTick
from ..services.baselines import active_baseline
from ..services.rebaseline import metrics as baseline_metrics
from ..services.planning import Plan, evm
from ..services.simulation import Scenario, initial_snapshot, ready_assignments, step
from ..domain import Phase,ProjectStatus
from ..models import Project


def json_value(value):
    # Decimal ratios remain exact strings; RNG tuples become portable JSON lists.
    return json.loads(json.dumps(value, default=str))


class SimulationState(TypedDict):
    run_id: str
    snapshot: dict
    change_approval_id: str
    closure_approval_id: str
    closure_artifact_id: str
    closure_decision: dict
    closure_result: str
    report_id: str | None


class SimulationWorkflow:
    def __init__(self, runtime, saver):
        self.runtime = runtime
        graph = StateGraph(SimulationState)
        graph.add_node('initialize', self.initialize)
        graph.add_node('tick', self.tick)
        from .simulation_management import prepare_change,review_change
        graph.add_node('prepare_change', lambda state: prepare_change(self,state))
        graph.add_node('review_change', lambda state: review_change(self,state))
        from .closure import prepare,review,archive
        graph.add_node('prepare_closure',lambda state:prepare(self,state))
        graph.add_node('review_acceptance',lambda state:review(self,state))
        graph.add_node('archive_closure',lambda state:archive(self,state))
        graph.add_edge('prepare_closure','review_acceptance')
        graph.add_edge('review_acceptance','archive_closure')
        graph.add_edge('archive_closure',END)
        graph.add_edge('prepare_change','review_change')
        graph.add_conditional_edges('review_change',self.route)
        graph.add_edge(START, 'initialize')
        graph.add_edge('initialize', 'tick')
        graph.add_conditional_edges('tick', self.route)
        self.graph = graph.compile(checkpointer=saver)

    def route(self,state):
        _,scenario,_=self.load(state['run_id'])
        if scenario.formal_management and state['snapshot']['change_triggered'] and not state['snapshot'].get('change_resolved'):
            return 'prepare_change'
        if all(p['accepted_day'] is not None for p in state['snapshot']['tasks'].values()):
            return 'prepare_closure' if scenario.final_acceptance else END
        return 'tick'

    @staticmethod
    def config(run_id, limit):
        return {'configurable': {'thread_id': f'{run_id}:simulation:v1'}, 'recursion_limit': limit+10}

    def load(self, run_id):
        with self.runtime.sessions() as session:
            row = session.get(SimulationRun, run_id)
            return Plan.model_validate(row.plan), Scenario.model_validate(row.scenario), row.seed

    def persist_tick(self, session, run_id, snapshot, events, metrics, assignments):
        if snapshot.get('baseline_id'):
            run=session.get(Run,run_id)
            project=session.get(Project,run.project_id)
            project.simulation_day=snapshot['day']
            project.phase=Phase.EXECUTING if snapshot['day']==0 else Phase.MONITORING_CONTROLLING
            project.status=ProjectStatus.RUNNING
        session.add(SimulationTick(run_id=run_id, day=snapshot['day'], snapshot=json_value(snapshot),
            metrics=json_value(metrics), events=json_value(events), assignments=assignments))
        for event in events:
            self.runtime.emit(session, run_id, event['kind'], event)
            session.flush()  # Sequence allocation must observe each event in this transaction.
        self.runtime.emit(session, run_id, 'simulation_metrics', json_value(metrics))

    def cached(self, run_id, day):
        with self.runtime.sessions() as session:
            row = session.scalar(select(SimulationTick).where(SimulationTick.run_id == run_id, SimulationTick.day == day))
            return row.snapshot if row else None

    def initialize(self, state):
        cached = self.cached(state['run_id'], 0)
        if cached is not None:
            return {'snapshot': cached}
        plan, _, seed = self.load(state['run_id'])
        snapshot = initial_snapshot(plan, seed)
        with self.runtime.sessions.begin() as session:
            _,scenario,_=self.load(state['run_id'])
            if scenario.formal_management:
                run=session.get(Run,state['run_id'])
                baseline=active_baseline(session,run.project_id)
                if not baseline or baseline.content['plan']!=plan.model_dump(mode='json'):
                    raise ValueError('Formal simulation requires matching approved baseline')
                snapshot['baseline_id']=baseline.id
            self.persist_tick(session, state['run_id'], snapshot, [], evm(plan,0,set(),{}), [])
        return {'snapshot': json_value(snapshot)}

    def tick(self, state):
        day = state['snapshot']['day'] + 1
        cached = self.cached(state['run_id'], day)
        if cached is not None:
            return {'snapshot': cached}
        plan, scenario, _ = self.load(state['run_id'])
        if scenario.formal_management:
            with self.runtime.sessions() as session:
                baseline=session.get(Baseline,state['snapshot']['baseline_id'])
                run=session.get(Run,state['run_id'])
                if active_baseline(session,run.project_id).id != baseline.id:
                    raise ValueError('Approved baseline changed without a simulation transition')
                plan=Plan.model_validate(baseline.content['plan'])
        assignments = ready_assignments(plan, state['snapshot'])
        if scenario.formal_management:
            from .execution_agents import developer,dispatch
            allocation=dispatch(self.runtime,state['run_id'],plan,state['snapshot'])
            assignments=allocation.payload['task_ids']
            decision=developer(self.runtime,state['run_id'],state['snapshot'],assignments)
            assignments=[action['task_id'] for action in decision.payload['actions']]
        snapshot, events, metrics = step(plan, state['snapshot'], scenario, assignments)
        if scenario.formal_management:
            metrics=baseline_metrics(plan,snapshot)
            from .execution_agents import tester_and_analyst
            tester_and_analyst(self.runtime,state['run_id'],snapshot,events,metrics,baseline.content['schedule'])
        with self.runtime.sessions.begin() as session:
            self.persist_tick(session, state['run_id'], snapshot, events, metrics, assignments)
        return {'snapshot': json_value(snapshot)}

    def drive(self, run_id):
        try:
            _, scenario, _ = self.load(run_id)
            config = self.config(run_id, scenario.max_days)
            existing = self.graph.get_state(config)
            value=Command(resume=True) if any(task.interrupts for task in existing.tasks) else (None if existing.values else {'run_id':run_id})
            self.graph.invoke(value, config)
            final=self.graph.get_state(config)
            paused=bool(final.next)
            if paused:
                status='waiting_acceptance' if final.values.get('closure_approval_id') else 'waiting_change'
            elif final.values.get('closure_result'):
                status='completed' if final.values['closure_result']=='approve' else 'acceptance_rejected'
            else:
                status='awaiting_m4'
            with self.runtime.sessions.begin() as session:
                row = session.get(SimulationRun,run_id)
                row.status, row.error = status, None
        except Exception as exc:
            with self.runtime.sessions.begin() as session:
                row = session.get(SimulationRun,run_id)
                row.status, row.error = 'failed', type(exc).__name__
