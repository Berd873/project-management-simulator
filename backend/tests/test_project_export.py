from datetime import date
from decimal import Decimal
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.planning import Dependency,Plan,PlannedTask,Resource
from app.services.project_export import NAMESPACE,export_project_xml

NS={'p':NAMESPACE}


def sample():
    return Plan(tasks=[PlannedTask(id='A',title='图书 & <编目>',duration_days=2,budget_cents=101,resource_id='dev'),
        PlannedTask(id='B',title='查询',duration_days=1,budget_cents=99,resource_id='dev')],
        dependencies=[Dependency(predecessor='A',successor='B',lag_days=1)],resources=[Resource(id='dev',rate_cents_per_day=50)])


def test_mspdi_workdays_costs_dependencies_and_no_fake_actuals():
    source=sample()
    data=export_project_xml(source,'图书馆 & 实验',date(2026,11,20))
    root=ET.fromstring(data)
    assert root.tag==f'{{{NAMESPACE}}}Project'
    assert root.findtext('p:CurrencyCode',namespaces=NS)=='CNY'
    assert root.findtext('p:MinutesPerDay',namespaces=NS)=='480'
    tasks=root.findall('p:Tasks/p:Task',NS)
    assert len(tasks)==2
    first,second=tasks
    assert first.findtext('p:Name',namespaces=NS)=='图书 & <编目>'
    assert first.findtext('p:Start',namespaces=NS)=='2026-11-20T08:00:00'
    assert first.findtext('p:Finish',namespaces=NS)=='2026-11-23T17:00:00'
    assert second.findtext('p:Start',namespaces=NS)=='2026-11-25T08:00:00'
    assert first.findtext('p:Duration',namespaces=NS)=='PT16H0M0S'
    assert sum(Decimal(t.findtext('p:FixedCost',namespaces=NS)) for t in tasks)==Decimal('2.00')
    assert second.findtext('p:PredecessorLink/p:PredecessorUID',namespaces=NS)==first.findtext('p:UID',namespaces=NS)
    assert second.findtext('p:PredecessorLink/p:Type',namespaces=NS)=='1'
    assert second.findtext('p:PredecessorLink/p:LinkLag',namespaces=NS)=='4800'
    assert all(t.findtext('p:PercentComplete',namespaces=NS)=='0' for t in tasks)
    assert not root.findall('.//p:ActualCost',NS) and not root.findall('.//p:ActualWork',NS)
    assert 'SIMULATION' in first.findtext('p:Notes',namespaces=NS)
    weekdays=root.findall('p:Calendars/p:Calendar/p:WeekDays/p:WeekDay',NS)
    assert len(weekdays)==7
    assert [d.findtext('p:DayWorking',namespaces=NS) for d in weekdays]==['0','1','1','1','1','1','0']


def test_export_stable_uids_across_revisions_and_detects_collision(monkeypatch):
    source=sample()
    added=PlannedTask(id='0-new',title='新增',duration_days=1,budget_cents=1,resource_id='dev')
    changed=source.model_copy(update={'version':2,'tasks':[added,*source.tasks]})
    def mapping(plan):
        root=ET.fromstring(export_project_xml(plan,'Example',date(2026,11,16)))
        return {t.findtext('p:WBS',namespaces=NS):t.findtext('p:UID',namespaces=NS) for t in root.findall('p:Tasks/p:Task',NS)}
    before,after=mapping(source),mapping(changed)
    assert all(after[key]==uid for key,uid in before.items())
    monkeypatch.setattr('app.services.project_export.stable_uid',lambda _:1)
    with pytest.raises(ValueError,match='collision'):
        export_project_xml(source,'Example',date(2026,11,16))


def test_export_api_versions_are_readonly_and_project_runs_reopen(tmp_path):
    with TestClient(create_app(f'sqlite:///{(tmp_path/"export.db").as_posix()}')) as c:
        p=c.post('/api/v1/projects',json={'name':'Library Management System','description':'Library catalog, readers, borrowing, returns and search'}).json()['id']
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'export'}).json()['run_id']
        before=c.get(f'/api/v1/runs/{run}/baselines').json()
        for version,count in [(1,4),(2,5)]:
            response=c.get(f'/api/v1/runs/{run}/export?baseline_version={version}&start_date=2026-11-16')
            assert response.status_code==200,response.text
            assert 'attachment' in response.headers['content-disposition']
            assert response.headers['x-execution-mode']=='simulation'
            root=ET.fromstring(response.content)
            assert len(root.findall('p:Tasks/p:Task',NS))==count
        assert c.get(f'/api/v1/runs/{run}/baselines').json()==before
        assert c.get(f'/api/v1/projects/{p}/runs').json()==[{'id':run,'status':'completed','delivery':True}]
        assert c.get(f'/api/v1/runs/{run}/export?baseline_version=999').status_code==404
        assert c.get(f'/api/v1/runs/{run}/export?format=csv').status_code==422
        assert c.get('/api/v1/runs/missing/export').status_code==404
