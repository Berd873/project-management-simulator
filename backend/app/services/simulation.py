"""Pure simulation ticks. No real source code is developed or tested here."""
from copy import deepcopy
import random

from pydantic import Field

from .planning import Plan, ValueObject, cpm, evm


class Scenario(ValueObject):
    version: str = 'lms-v1'
    forced_first_test_failures: list[str] = Field(default_factory=list)
    defect_probability: float = Field(default=0.0, ge=0, le=1)
    max_days: int = Field(default=120, gt=0)
    max_repairs: int = Field(default=3, ge=0)
    change_trigger_day: int | None = Field(default=None, ge=1)
    formal_management: bool = False
    final_acceptance: bool = False


def initial_snapshot(plan: Plan, seed: int) -> dict:
    cpm(plan)  # Reject cycles before the first tick.
    if type(seed) is not int or seed < 0:
        raise ValueError('Invalid seed')
    return {'engine_version': '1', 'plan_version': plan.version, 'day': 0,
            'rng_state': random.Random(seed).getstate(), 'change_triggered': False,
            'tasks': {t.id: {'work_done': 0, 'rework_left': 0, 'attempts': 0,
                           'accepted_day': None, 'actual_cost_cents': 0} for t in plan.tasks}}


def tuple_tree(value):
    return tuple(tuple_tree(v) for v in value) if isinstance(value, (tuple, list)) else value


def ready_assignments(plan: Plan, snapshot: dict) -> list[str]:
    """Deterministic feasible assignment proposal; the workflow authorizes execution."""
    remaining = {r.id: r.capacity for r in plan.resources}
    ready = []
    for task in sorted(plan.tasks, key=lambda task: task.id):
        if snapshot['tasks'][task.id]['accepted_day'] is not None:
            continue
        if any(snapshot['tasks'][edge.predecessor]['accepted_day'] is None
               or snapshot['tasks'][edge.predecessor]['accepted_day'] + edge.lag_days > snapshot['day']
               for edge in plan.dependencies if edge.successor == task.id):
            continue
        if remaining[task.resource_id]:
            ready.append(task.id)
            remaining[task.resource_id] -= 1
    return ready


def eligible_assignments(plan: Plan, snapshot: dict) -> list[str]:
    """All precedence-feasible tasks, before the PM selects resource-feasible work."""
    return [task.id for task in sorted(plan.tasks,key=lambda task:task.id)
        if snapshot['tasks'][task.id]['accepted_day'] is None
        and all(snapshot['tasks'][edge.predecessor]['accepted_day'] is not None
                and snapshot['tasks'][edge.predecessor]['accepted_day']+edge.lag_days<=snapshot['day']
                for edge in plan.dependencies if edge.successor==task.id)]


def step(plan: Plan, previous: dict, scenario: Scenario, authorized_ids: list[str]) -> tuple[dict, list[dict], dict]:
    """Advance one workday using explicit authorized assignments, preserving caller inputs."""
    ids = {t.id for t in plan.tasks}
    if set(previous['tasks']) != ids or previous['plan_version'] != plan.version:
        raise ValueError('Snapshot and plan mismatch')
    if previous['engine_version'] != '1':
        raise ValueError('Unsupported engine version')
    if not set(scenario.forced_first_test_failures) <= ids:
        raise ValueError('Scenario references unknown task')
    if len(authorized_ids) != len(set(authorized_ids)) or not set(authorized_ids) <= ids:
        raise ValueError('Invalid authorized task IDs')
    if previous['day'] >= scenario.max_days:
        raise ValueError('Simulation day limit exceeded')
    if all(t['accepted_day'] is not None for t in previous['tasks'].values()):
        raise ValueError('Simulation already finished')
    current = deepcopy(previous)
    day = previous['day']
    current['day'] = day + 1
    resources = {r.id: r for r in plan.resources}
    occupied = {r: 0 for r in resources}
    tasks = {t.id: t for t in plan.tasks}
    rng = random.Random()
    rng.setstate(tuple_tree(previous['rng_state']))
    events = []
    def emit(kind, **payload):
        events.append({'kind': kind, 'day': day+1, 'execution_mode': 'simulation', **payload})
    for key in sorted(authorized_ids):
        task = tasks[key]
        progress = current['tasks'][key]
        if progress['accepted_day'] is not None:
            raise ValueError('Cannot execute an accepted task')
        if any(previous['tasks'][e.predecessor]['accepted_day'] is None
               or previous['tasks'][e.predecessor]['accepted_day'] + e.lag_days > day
               for e in plan.dependencies if e.successor == key):
            raise ValueError('Predecessors are not accepted or dependency lag not reached')
        resource = resources[task.resource_id]
        occupied[resource.id] += 1
        if occupied[resource.id] > resource.capacity:
            raise ValueError('Resource capacity exceeded')
        progress['actual_cost_cents'] += resource.rate_cents_per_day
        if progress['rework_left']:
            progress['rework_left'] -= 1
            emit('simulated_repair', task_id=key)
        else:
            progress['work_done'] += 1
            emit('simulated_development', task_id=key)
        if progress['work_done'] >= task.duration_days and progress['rework_left'] == 0:
            progress['attempts'] += 1
            failed = (progress['attempts'] == 1 and key in scenario.forced_first_test_failures) or rng.random() < scenario.defect_probability
            if failed:
                emit('simulated_test_failed', task_id=key, attempt=progress['attempts'])
                if progress['attempts'] > scenario.max_repairs:
                    raise ValueError('Repair limit exceeded')
                progress['rework_left'] = 1
            else:
                progress['accepted_day'] = day + 1
                emit('simulated_test_passed', task_id=key, attempt=progress['attempts'])
    if scenario.change_trigger_day is not None and current['day'] >= scenario.change_trigger_day and not current['change_triggered']:
        current['change_triggered'] = True
        emit('change_requested', description='Add overdue reminders', status='proposal_only')
    current['rng_state'] = rng.getstate()
    accepted = {key for key, p in current['tasks'].items() if p['accepted_day'] is not None}
    metrics = evm(plan, current['day'], accepted, {k: p['actual_cost_cents'] for k, p in current['tasks'].items()})
    return current, events, metrics
