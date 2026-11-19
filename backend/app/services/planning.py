from datetime import date, timedelta
from decimal import Decimal
import heapq

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValueObject(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class PlannedTask(ValueObject):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    duration_days: int = Field(gt=0)
    budget_cents: int = Field(ge=0)
    resource_id: str = Field(min_length=1)


class Dependency(ValueObject):
    predecessor: str
    successor: str
    lag_days: int = Field(default=0, ge=0)


class Resource(ValueObject):
    id: str
    capacity: int = Field(default=1, gt=0)
    rate_cents_per_day: int = Field(ge=0)


class Plan(ValueObject):
    version: int = Field(default=1, gt=0)
    tasks: list[PlannedTask] = Field(min_length=1)
    dependencies: list[Dependency] = Field(default_factory=list)
    resources: list[Resource] = Field(min_length=1)

    @model_validator(mode='after')
    def references(self):
        ids = {t.id for t in self.tasks}
        resources = {r.id for r in self.resources}
        if len(ids) != len(self.tasks) or len(resources) != len(self.resources):
            raise ValueError('Duplicate task/resource IDs')
        if any(t.resource_id not in resources for t in self.tasks):
            raise ValueError('Unknown resource')
        seen = set()
        for edge in self.dependencies:
            pair = (edge.predecessor, edge.successor)
            if edge.predecessor not in ids or edge.successor not in ids:
                raise ValueError('Unknown dependency task')
            if edge.predecessor == edge.successor or pair in seen:
                raise ValueError('Self or duplicate dependency')
            seen.add(pair)
        return self


def cpm(plan: Plan) -> dict:
    """FS dependency CPM, half-open workday intervals; excludes resource leveling."""
    tasks = {t.id: t for t in plan.tasks}
    predecessors = {key: [] for key in tasks}
    successors = {key: [] for key in tasks}
    for edge in plan.dependencies:
        predecessors[edge.successor].append((edge.predecessor, edge.lag_days))
        successors[edge.predecessor].append((edge.successor, edge.lag_days))
    degrees = {key: len(value) for key, value in predecessors.items()}
    ready = [key for key, count in degrees.items() if count == 0]
    heapq.heapify(ready)
    order, rows = [], {}
    while ready:
        key = heapq.heappop(ready)
        order.append(key)
        start = max((rows[p]['ef'] + lag for p, lag in predecessors[key]), default=0)
        rows[key] = {'es': start, 'ef': start + tasks[key].duration_days}
        for child, _ in successors[key]:
            degrees[child] -= 1
            if degrees[child] == 0:
                heapq.heappush(ready, child)
    if len(order) != len(tasks):
        raise ValueError('Dependency cycle')
    duration = max(row['ef'] for row in rows.values())
    for key in reversed(order):
        finish = min((rows[s]['ls'] - lag for s, lag in successors[key]), default=duration)
        rows[key].update(lf=finish, ls=finish - tasks[key].duration_days)
        rows[key]['total_float'] = rows[key]['ls'] - rows[key]['es']
    critical = sorted(key for key, row in rows.items() if row['total_float'] == 0)
    critical_edges = sorted((e.predecessor, e.successor) for e in plan.dependencies
        if e.predecessor in critical and e.successor in critical
        and rows[e.predecessor]['ef'] + e.lag_days == rows[e.successor]['es'])
    return {'duration_days': duration, 'tasks': rows, 'critical_task_ids': critical, 'critical_edges': critical_edges}


def workday_date(start: date, offset: int) -> date:
    if type(offset) is not int or offset < 0:
        raise ValueError('Workday offset must be a nonnegative integer')
    day = start
    while day.weekday() >= 5:
        day += timedelta(days=1)
    for _ in range(offset):
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    return day


def planned_value(task: PlannedTask, start_day: int, status_day: int) -> int:
    """Uniform daily cents; all indivisible remainder is assigned to final day."""
    elapsed = min(task.duration_days, max(0, status_day - start_day))
    if elapsed == task.duration_days:
        return task.budget_cents
    return (task.budget_cents // task.duration_days) * elapsed


def evm(plan: Plan, status_day: int, accepted_ids: set[str], actual_costs: dict[str, int], pv_override_cents: int | None=None) -> dict:
    if type(status_day) is not int or status_day < 0:
        raise ValueError('Invalid status day')
    ids = {t.id for t in plan.tasks}
    if not accepted_ids <= ids or not set(actual_costs) <= ids:
        raise ValueError('Unknown task in EVM input')
    if any(type(cost) is not int or cost < 0 for cost in actual_costs.values()):
        raise ValueError('Actual costs must be nonnegative integer cents')
    schedule = cpm(plan)
    pv = sum(planned_value(t, schedule['tasks'][t.id]['es'], status_day) for t in plan.tasks)
    ev = sum(t.budget_cents for t in plan.tasks if t.id in accepted_ids)
    ac = sum(actual_costs.values())
    bac = sum(t.budget_cents for t in plan.tasks)
    if pv_override_cents is not None:
        if type(pv_override_cents) is not int or not 0 <= pv_override_cents <= bac:
            raise ValueError('Invalid planned value override')
        pv = pv_override_cents
    spi = Decimal(ev) / Decimal(pv) if pv else None
    cpi = Decimal(ev) / Decimal(ac) if ac else None
    eac = Decimal(bac) / cpi if cpi else None
    return {'baseline_version': plan.version, 'status_day': status_day, 'pv_cents': pv, 'ev_cents': ev,
            'ac_cents': ac, 'bac_cents': bac, 'sv_cents': ev-pv, 'cv_cents': ev-ac,
            'spi': spi, 'cpi': cpi, 'eac_cents': eac,
            'etc_cents': eac-ac if eac is not None else None,
            'vac_cents': bac-eac if eac is not None else None,
            'undefined_reasons': {k: reason for k, reason, undefined in [
                ('spi','PV is zero',pv == 0), ('cpi','AC is zero',ac == 0),
                ('eac','CPI is zero or undefined',not cpi)] if undefined},
            'forecast_assumption': 'Future cost efficiency equals current CPI', 'execution_mode': 'simulation'}
