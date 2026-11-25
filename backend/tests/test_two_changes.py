from fastapi.testclient import TestClient
from app.main import create_app
from app.agents.providers import MockProvider

class TicketingProvider(MockProvider):
    def generate(self, context):
        raw=super().generate(context)
        if context.operation=='proposal' and context.role.value=='requirements_analyst':
            raw['payload']={'in_scope':['Campus ticketing'], 'out_scope':['Actual payments'], 'tasks':[
                {'id':str(i),'title':title,'acceptance_criteria':[title+' simulated acceptance'],
                 'predecessor_ids':[] if i<3 else [str(i-2)]}
                for i,title in enumerate(['活动发布','报名名额','支付沙箱','电子票','现场核销','联调验收'],1)]}
        if context.operation=='propose_change':
            raw['payload']['added_tasks'][0]['id']='change.'+str(len(context.facts['current_plan']['tasks']))
        return raw

def test_two_changes_create_three_baselines_and_survive_restart(tmp_path):
    url=f"sqlite:///{(tmp_path/'two.db').as_posix()}"
    with TestClient(create_app(url,provider=TicketingProvider())) as c:
        p=c.post('/api/v1/projects',json={'name':'校园活动票务平台','description':'Campus ticketing platform','llm_mode':'mock'}).json()['id']
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'two'}).json()['run_id']
        status=c.get(f'/api/v1/runs/{run}/delivery').json()
        assert status['status']=='completed',status
        changes=c.get(f'/api/v1/runs/{run}/changes').json()
        assert len(changes)==2 and all(row['status']=='applied' for row in changes)
        baselines=c.get(f'/api/v1/runs/{run}/baselines').json()
        assert [row['version'] for row in baselines]==[1,2,3]
        report=c.get(f'/api/v1/runs/{run}/simulation/report').json()
        assert report['accepted'] and len(report['report']['scope_acceptance'])==8
    with TestClient(create_app(url,provider=TicketingProvider())) as c:
        assert c.get(f'/api/v1/runs/{run}/simulation/report').json()==report


def test_two_human_changes_have_separate_gates_after_service_restarts(tmp_path):
    url=f"sqlite:///{(tmp_path/'human-two.db').as_posix()}"
    with TestClient(create_app(url,provider=TicketingProvider())) as c:
        p=c.post('/api/v1/projects',json={'name':'校园活动票务','description':'Campus ticketing','sponsor_mode':'human'}).json()['id']
        run=c.post(f'/api/v1/projects/{p}/delivery',headers={'Idempotency-Key':'two-human'}).json()['run_id']
    kinds=[]
    for _ in range(5):
        with TestClient(create_app(url,provider=TicketingProvider())) as c:
            prefix=f'/api/v1/runs/{run}'
            status=c.get(prefix+'/delivery').json()
            assert status['status']=='waiting_approval',status
            a=status['pending_approvals'][0];kinds.append(a['kind'])
            path=(prefix+f"/approvals/{a['id']}" if a['kind']=='project_manager' else
                  prefix+f"/plan-approvals/{a['id']}/decision" if a['kind']=='plan' else prefix+'/simulation/acceptance')
            assert c.post(path,json={'target_id':a['target_id'],'target_version':a['target_version'],'decision':'approve','reason':'Reviewed current version'}).status_code==202
            assert c.post(prefix+'/delivery/resume').status_code==202
    with TestClient(create_app(url,provider=TicketingProvider())) as c:
        assert c.get(prefix+'/delivery').json()['status']=='completed'
        assert len(c.get(prefix+'/baselines').json())==3
    assert kinds==['project_manager','plan','plan','plan','closure_candidate']
