"""Deterministic migration of remaining work without rewriting historical execution."""
from copy import deepcopy

from .baselines import BaselineConflict, analyze_change
from .planning import Plan, cpm, evm


def transition(source: Plan, proposed: Plan, snapshot: dict, frozen_pv_cents: int) -> dict:
    accepted = {key for key,p in snapshot['tasks'].items() if p['accepted_day'] is not None}
    analyze_change(source,proposed,accepted)
    if snapshot['plan_version'] != source.version:
        raise BaselineConflict('Snapshot does not match source plan')
    old, new = {t.id:t for t in source.tasks},{t.id:t for t in proposed.tasks}
    for key, progress in snapshot['tasks'].items():
        started = progress['work_done'] or progress['actual_cost_cents'] or progress['attempts']
        if started and (key not in new or new[key] != old[key]):
            raise BaselineConflict('Started work cannot be removed or reestimated in place; add a new task')
        if started:
            old_edges = [e.model_dump() for e in source.dependencies if e.successor==key]
            new_edges = [e.model_dump() for e in proposed.dependencies if e.successor==key]
            if old_edges != new_edges:
                raise BaselineConflict('Started task dependencies cannot change')
    result = deepcopy(snapshot)
    result['tasks'] = {key:deepcopy(snapshot['tasks'][key]) if key in snapshot['tasks'] else {
        'work_done':0,'rework_left':0,'attempts':0,'accepted_day':None,'actual_cost_cents':0} for key in new}
    result['plan_version'] = proposed.version
    result['change_resolved'] = True
    day = snapshot['day']
    schedule = cpm(proposed)
    forecast = {}
    for key in sorted(new,key=lambda key:(schedule['tasks'][key]['es'],key)):
        progress = result['tasks'][key]
        if progress['accepted_day'] is not None:
            forecast[key] = {'start':progress['accepted_day']-new[key].duration_days,'finish':progress['accepted_day']}
            continue
        start = max([day]+[forecast[e.predecessor]['finish']+e.lag_days for e in proposed.dependencies if e.successor==key])
        remaining = new[key].duration_days-progress['work_done']+progress['rework_left']
        forecast[key] = {'start':start,'finish':start+remaining}
    bac = sum(t.budget_cents for t in proposed.tasks)
    if type(frozen_pv_cents) is not int or not 0 <= frozen_pv_cents <= bac:
        raise BaselineConflict('New BAC cannot be less than already accrued planned value')
    finish = max(row['finish'] for row in forecast.values())
    if finish <= day and frozen_pv_cents != bac:
        raise BaselineConflict('No remaining work to allocate future planned value')
    result['pv_anchor'] = {'day':day,'pv_cents':frozen_pv_cents,'finish_day':finish,'bac_cents':bac,
                           'assumption':'Uniform remaining aggregate PV over dependency-only remaining forecast'}
    result['remaining_forecast'] = forecast
    return result


def metrics(plan: Plan, snapshot: dict) -> dict:
    anchor = snapshot.get('pv_anchor')
    pv = None
    if anchor:
        if snapshot['day'] < anchor['day']:
            raise BaselineConflict('Cannot recompute pre-change metrics with the new baseline')
        duration = anchor['finish_day']-anchor['day']
        elapsed = min(duration,snapshot['day']-anchor['day'])
        remaining = anchor['bac_cents']-anchor['pv_cents']
        pv = anchor['bac_cents'] if elapsed==duration else anchor['pv_cents']+(remaining//duration)*elapsed
    accepted = {key for key,p in snapshot['tasks'].items() if p['accepted_day'] is not None}
    result = evm(plan,snapshot['day'],accepted,{key:p['actual_cost_cents'] for key,p in snapshot['tasks'].items()},pv_override_cents=pv)
    if anchor:
        result['pv_assumption'] = anchor['assumption']
    if 'baseline_id' in snapshot:
        result['baseline_id'] = snapshot['baseline_id']
    return result
