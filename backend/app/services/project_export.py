"""MSPDI task-plan export. Exports plans, never simulated outcomes as actual work."""
from datetime import date
from decimal import Decimal
from hashlib import sha256
import xml.etree.ElementTree as ET

from .planning import Plan,cpm,workday_date

NAMESPACE='http://schemas.microsoft.com/project'
ET.register_namespace('',NAMESPACE)


def stable_uid(task_id: str) -> int:
    return (int.from_bytes(sha256(task_id.encode('utf-8')).digest()[:4],'big') & 0x7fffffff) or 1


def export_project_xml(plan: Plan,project_name: str,start_date: date,project_id: str='simulation-plan') -> bytes:
    schedule=cpm(plan)
    if schedule['duration_days']>100000:
        raise ValueError('Plan exceeds supported export calendar range')
    ids={task.id:stable_uid(task.id) for task in plan.tasks}
    if len(set(ids.values()))!=len(ids):
        raise ValueError('Stable task UID collision; export cannot safely map dependencies')
    def node(parent,name,value=None):
        child=ET.SubElement(parent,f'{{{NAMESPACE}}}{name}')
        if value is not None:
            text=str(value)
            child.text=''.join(c if ord(c) in (9,10,13) or 32<=ord(c)<=0xd7ff or 0xe000<=ord(c)<=0xfffd or 0x10000<=ord(c)<=0x10ffff else '\ufffd' for c in text)
        return child
    def timestamp(offset,finish=False):
        return workday_date(start_date,offset).isoformat()+('T17:00:00' if finish else 'T08:00:00')
    root=ET.Element(f'{{{NAMESPACE}}}Project')
    fields=[('SaveVersion',12),('UID',project_id),('Name',project_name),('Title',f'SIMULATION PLAN · {project_name} · Baseline V{plan.version}'),
            ('Subject','Teaching simulation; dependency-only approved task plan; not real execution results'),
            ('ScheduleFromStart',1),('StartDate',timestamp(0)),('FinishDate',timestamp(schedule['duration_days']-1,True)),
            ('CurrencyDigits',2),('CurrencySymbol','¥'),('CurrencyCode','CNY'),('CurrencySymbolPosition',0),
            ('CalendarUID',1),('DefaultStartTime','08:00:00'),('DefaultFinishTime','17:00:00'),
            ('MinutesPerDay',480),('MinutesPerWeek',2400),('DaysPerMonth',20),('DefaultTaskType',1),('DurationFormat',7),('WeekStartDay',1)]
    for name,value in fields:
        node(root,name,value)
    calendar=node(node(root,'Calendars'),'Calendar')
    for name,value in [('UID',1),('Name','Standard 5-day / 8-hour teaching calendar'),('IsBaseCalendar',1),('BaseCalendarUID',-1)]:
        node(calendar,name,value)
    weekdays=node(calendar,'WeekDays')
    for day in range(1,8):  # MSPDI Sunday=1, Monday=2, Saturday=7.
        weekday=node(weekdays,'WeekDay')
        node(weekday,'DayType',day)
        working=day not in (1,7)
        node(weekday,'DayWorking',int(working))
        if working:
            times=node(weekday,'WorkingTimes')
            for start,end in [('08:00:00','12:00:00'),('13:00:00','17:00:00')]:
                period=node(times,'WorkingTime')
                node(period,'FromTime',start);node(period,'ToTime',end)
    tasks=node(root,'Tasks')
    for position,task in enumerate(plan.tasks,1):
        row=node(tasks,'Task')
        timing=schedule['tasks'][task.id]
        cost=f'{Decimal(task.budget_cents)/100:.2f}'
        fields=[('UID',ids[task.id]),('ID',position),('Name',task.title[:512]),('Type',1),('IsNull',0),
                ('WBS',task.id),('OutlineNumber',position),('OutlineLevel',1),('Start',timestamp(timing['es'])),
                ('Finish',timestamp(timing['ef']-1,True)),('Duration',f'PT{task.duration_days*8}H0M0S'),('DurationFormat',7),
                ('Estimated',0),('Milestone',0),('Summary',0),('Critical',int(task.id in schedule['critical_task_ids'])),
                ('FixedCost',cost),('FixedCostAccrual',3),('PercentComplete',0),('Cost',cost),('CalendarUID',1),
                ('Notes',f'SIMULATION PLAN ONLY; baseline V{plan.version}; resource={task.resource_id}; budget exported as fixed cost; resource assignments and actual execution are not exported.')]
        for name,value in fields:
            node(row,name,value)
        for dependency in plan.dependencies:
            if dependency.successor==task.id:
                link=node(row,'PredecessorLink')
                node(link,'PredecessorUID',ids[dependency.predecessor]);node(link,'Type',1)
                node(link,'CrossProject',0);node(link,'LinkLag',dependency.lag_days*4800);node(link,'LagFormat',7)
    ET.indent(root,space='  ')
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)
