from copy import deepcopy
from datetime import date
from decimal import Decimal
import json

import pytest

from app.services.planning import Dependency, Plan, PlannedTask, Resource, cpm, evm, planned_value, workday_date
from app.services.simulation import Scenario, initial_snapshot, step


def task(key, days, budget=100, resource='dev'):
    return PlannedTask(id=key, title=key, duration_days=days, budget_cents=budget, resource_id=resource)


def plan(tasks=None, dependencies=None, capacity=2):
    return Plan(tasks=tasks or [task('A',2), task('B',3), task('C',1)],
                dependencies=dependencies if dependencies is not None else [Dependency(predecessor='A',successor='C'),Dependency(predecessor='B',successor='C')],
                resources=[Resource(id='dev',capacity=capacity,rate_cents_per_day=50)])


def test_cpm_hand_calculated_diamond_and_stable_order():
    p = plan()
    result = cpm(p)
    assert result['duration_days'] == 4
    assert result['tasks'] == {
        'A': {'es':0,'ef':2,'ls':1,'lf':3,'total_float':1},
        'B': {'es':0,'ef':3,'ls':0,'lf':3,'total_float':0},
        'C': {'es':3,'ef':4,'ls':3,'lf':4,'total_float':0},
    }
    assert result['critical_task_ids'] == ['B','C']
    assert result['critical_edges'] == [('B','C')]
    assert cpm(p.model_copy(update={'tasks':list(reversed(p.tasks))})) == result


def test_cpm_multiple_critical_branches_and_lag():
    p = plan([task('A',2),task('B',2),task('C',1)], [Dependency(predecessor='A',successor='C',lag_days=1),Dependency(predecessor='B',successor='C',lag_days=1)])
    assert cpm(p)['critical_task_ids'] == ['A','B','C']
    assert cpm(p)['duration_days'] == 4


def test_cycle_and_invalid_references():
    with pytest.raises(ValueError, match='cycle'):
        cpm(plan([task('A',1),task('B',1)], [Dependency(predecessor='A',successor='B'),Dependency(predecessor='B',successor='A')]))
    for edges in [[Dependency(predecessor='A',successor='missing')], [Dependency(predecessor='A',successor='A')], [Dependency(predecessor='A',successor='C')]*2]:
        with pytest.raises(ValueError):
            plan(dependencies=edges)
    with pytest.raises(ValueError, match='Duplicate'):
        plan([task('A',1),task('A',1)], [])
    with pytest.raises(ValueError, match='Unknown resource'):
        plan([task('A',1,resource='missing')], [])


@pytest.mark.parametrize('days,budget', [(0,1),(-1,1),(1,-1),(True,1),(1,1.5)])
def test_strict_task_numbers(days,budget):
    with pytest.raises(ValueError):
        task('A',days,budget)


def test_pv_cents_and_workday_calendar():
    t = task('A',3,100)
    assert [planned_value(t,0,d) for d in range(5)] == [0,33,66,100,100]
    assert workday_date(date(2026,11,20),1) == date(2026,11,23)
    assert workday_date(date(2026,11,21),0) == date(2026,11,23)
    with pytest.raises(ValueError):
        workday_date(date(2026,11,20),-1)


def test_evm_hand_calculation_and_zero_denominators():
    p = plan([task('A',2,100),task('B',2,200)],[])
    m = evm(p,1,{'A'},{'A':80,'B':20})
    assert (m['pv_cents'],m['ev_cents'],m['ac_cents'],m['bac_cents']) == (150,100,100,300)
    assert m['sv_cents'] == -50
    assert m['cv_cents'] == 0
    assert m['spi'] == Decimal(100)/150
    assert m['cpi'] == 1
    assert (m['eac_cents'],m['etc_cents'],m['vac_cents']) == (300,200,0)
    initial = evm(p,0,set(),{})
    assert initial['spi'] is initial['cpi'] is initial['eac_cents'] is None
    assert set(initial['undefined_reasons']) == {'spi','cpi','eac'}
    assert evm(p,1,set(),{'A':100})['eac_cents'] is None


@pytest.mark.parametrize('accepted,costs', [({'unknown'},{}),(set(),{'unknown':1}),(set(),{'A':-1}),(set(),{'A':1.2})])
def test_evm_rejects_bad_inputs(accepted,costs):
    with pytest.raises(ValueError):
        evm(plan(),1,accepted,costs)


def test_simulated_repair_cost_ev_and_immutable_input():
    p = plan([task('A',1,100)],[])
    scenario = Scenario(forced_first_test_failures=['A'],change_trigger_day=1)
    before = initial_snapshot(p,42)
    saved = deepcopy(before)
    first, events, metrics = step(p,before,scenario,['A'])
    assert before == saved
    assert first['tasks']['A']['rework_left'] == 1
    assert metrics['ac_cents'] == 50 and metrics['ev_cents'] == 0
    assert [e['kind'] for e in events] == ['simulated_development','simulated_test_failed','change_requested']
    second, events, metrics = step(p,first,scenario,['A'])
    assert metrics['ev_cents'] == metrics['ac_cents'] == 100
    assert second['tasks']['A']['accepted_day'] == 2
    assert [e['kind'] for e in events] == ['simulated_repair','simulated_test_passed']
    assert all(e['execution_mode'] == 'simulation' for e in events)
    with pytest.raises(ValueError, match='finished'):
        step(p,second,scenario,[])


def test_tick_capacity_dependency_and_lag():
    p = plan(capacity=1)
    before = initial_snapshot(p,1)
    with pytest.raises(ValueError, match='capacity'):
        step(p,before,Scenario(),['A','B'])
    with pytest.raises(ValueError, match='Predecessors'):
        step(p,before,Scenario(),['C'])
    p = plan([task('A',1),task('B',1)],[Dependency(predecessor='A',successor='B',lag_days=1)])
    first,_,_ = step(p,initial_snapshot(p,1),Scenario(),['A'])
    with pytest.raises(ValueError, match='lag'):
        step(p,first,Scenario(),['B'])
    idle,_,_ = step(p,first,Scenario(),[])
    done,_,_ = step(p,idle,Scenario(),['B'])
    assert done['tasks']['B']['accepted_day'] == 3


def test_rng_resume_json_roundtrip_and_reproducibility():
    p = plan([task('A',2)],[])
    scenario = Scenario(defect_probability=0.5,max_repairs=10)
    first,_,_ = step(p,initial_snapshot(p,7),scenario,['A'])
    resumed = json.loads(json.dumps(first))
    assert step(p,resumed,scenario,['A']) == step(p,first,scenario,['A'])
    assert step(p,initial_snapshot(p,7),scenario,['A']) == step(p,initial_snapshot(p,7),scenario,['A'])


def test_simulation_bounds():
    p = plan([task('A',2)],[])
    first,_,_ = step(p,initial_snapshot(p,1),Scenario(),['A'])
    with pytest.raises(ValueError, match='day limit'):
        step(p,first,Scenario(max_days=1),['A'])
    p = plan([task('A',1)],[])
    with pytest.raises(ValueError, match='Repair limit'):
        step(p,initial_snapshot(p,1),Scenario(forced_first_test_failures=['A'],max_repairs=0),['A'])


def test_library_fixture_full_pure_engine_replay():
    from pathlib import Path
    from app.services.simulation import ready_assignments
    data = json.loads((Path(__file__).resolve().parents[2] / 'examples/library_management/scenario.json').read_text())
    p = Plan.model_validate(data['plan'])
    scenario = Scenario.model_validate(data['scenario'])
    def run():
        snapshot = initial_snapshot(p,data['seed'])
        events = []
        history = []
        for _ in range(scenario.max_days):
            snapshot, batch, metrics = step(p,snapshot,scenario,ready_assignments(p,snapshot))
            events.extend(batch)
            history.append(metrics)
            # Simulate persistence roundtrip after every step, including the RNG state.
            snapshot = json.loads(json.dumps(snapshot))
            if all(t['accepted_day'] is not None for t in snapshot['tasks'].values()):
                return snapshot, events, history
        pytest.fail('Fixture did not finish')
    snapshot, events, history = run()
    assert run() == (snapshot,events,history)
    assert cpm(p)['duration_days'] == 4
    assert snapshot['day'] == 7  # Resource waiting + one day of repair exceed resource-free CPM.
    assert history[-1]['pv_cents'] == history[-1]['ev_cents'] == 30000
    assert history[-1]['ac_cents'] == 35000
    assert history[-1]['cpi'] == Decimal(30000)/35000
    assert sum(e['kind'] == 'simulated_test_failed' for e in events) == 1
    assert sum(e['kind'] == 'simulated_repair' for e in events) == 1
    assert sum(e['kind'] == 'change_requested' for e in events) == 1
