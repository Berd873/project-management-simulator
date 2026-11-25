"""Real API course run. No Mock fallback; persistent DB and redacted evidence."""
import argparse,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from dotenv import load_dotenv
parser=argparse.ArgumentParser()
parser.add_argument('--resume-repaired',action='store_true',help='One explicit bounded recovery after a code correction; preserves exhausted traces')
parser.add_argument('--config',type=Path,required=True)
parser.add_argument('--output',type=Path,default=root/'output'/'real-ticketing')
args=parser.parse_args()
load_dotenv(args.config,override=True)
os.environ['LLM_MODEL']='qwen3.7-flash'
os.environ['LLM_TIMEOUT_SECONDS']='120'
os.environ['LLM_MAX_TOKENS']='4096'
from fastapi.testclient import TestClient
from app.main import create_app
from app.agents.providers import RealProvider
from app.models import Event,Approval
from sqlalchemy import select
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
if (out/'demo.db').exists() and not args.resume_repaired:
    raise SystemExit('Output already contains a run; use a new output directory to preserve evidence')
brief="""校园活动票务（Campus event ticketing）平台。教学模拟，不执行真实代码或资金交易。
初始范围恰好六项：活动发布、报名与名额、支付沙箱、电子票、在线核销、联调验收。请需求分析师使用任务ID 1—6，明确有向无环依赖与每项验收标准；不将后续退款或离线验票放入初始范围。
估算教学粒度：每项初始任务1个模拟工作日，两个资源backend和frontend，各容量1，每日费率分别80000分和60000分。末项联调验收依赖其余业务模块。测试由模拟引擎给出，其中末项首次测试失败后需修复回归。
项目运行中由流程分别发起CR-01退款申请与审批记录、CR-02离线验票与防重复核销。每次变更新增1项、1个模拟工作日，使用全新ID且沿用已有资源，不修改已开工或已验收任务。变更必须经过影响分析、Sponsor审批、基准更新。
PM每次在资源容量内优先推进可用任务，避免不必要等待；所有角色只返回约定Schema，不额外附加字段。Sponsor基于证据独立审批，合法且满足标准时可批准。"""
class AuditedReal(RealProvider):
    calls=0
    def invoke(self,kind,fn):
        self.calls+=1;number=self.calls;started=time.perf_counter()
        print(f'API {number}: {kind} ...',flush=True)
        record={'number':number,'kind':kind,'started_at':datetime.now(timezone.utc).isoformat(),'model':self.model}
        try:
            value=fn();record['http_success']=True
            return value
        except Exception as exc:
            record.update(http_success=False,error_type=type(exc).__name__)
            raise
        finally:
            record['elapsed_ms']=round((time.perf_counter()-started)*1000)
            with (out/'api-calls.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
            print(f"API {number}: {record.get('http_success')} ({record['elapsed_ms']}ms)",flush=True)
    def generate(self,context):
        value=self.invoke(context.role.value+':'+context.operation,lambda:super(AuditedReal,self).generate(context))
        if self.validation_feedback: print('VALIDATION:',self.validation_feedback[:500],flush=True)
        return value
    def approve(self,target,charter):
        return self.invoke('sponsor:approval',lambda:super(AuditedReal,self).approve(target,charter))
provider=AuditedReal(); provider.calls=len((out/'api-calls.jsonl').read_text(encoding='utf-8').splitlines()) if args.resume_repaired else 0
app=create_app('sqlite:///'+(out/'demo.db').as_posix(),provider=provider)
def save(name,value):
    (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
started=datetime.now(timezone.utc).isoformat()
with TestClient(app) as c:
    if args.resume_repaired:
        from app.models import AgentExecution,NodeReceipt
        old_manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
        save('failure-before-recovery',old_manifest)
        run=old_manifest['run_id'];started=old_manifest['started_at']
        with app.state.runtime.sessions.begin() as session:
            rows=session.scalars(select(AgentExecution).where(AgentExecution.run_id==run,AgentExecution.valid.is_(False))).all()
            counts={}
            for row in rows:counts[row.node]=counts.get(row.node,0)+1
            nodes={node for node,count in counts.items() if count==3 and ':repair' not in node}
            assert nodes,'No exhausted node to repair'
            app.state.runtime.repair_nodes=nodes
            session.add(NodeReceipt(run_id=run,node='explicit_provider_repair1',patch={'nodes':sorted(nodes),'reason':'Corrected nonexistent evidence references with empty-citation schema; original failed attempts retained','prompt_version':provider.prompt_version}))
        response=c.post(f'/api/v1/runs/{run}/delivery/resume')
    else:
        project=c.post('/api/v1/projects',json={'name':'校园活动票务平台 · 真实模型双变更实验','description':brief,'llm_mode':'real','sponsor_mode':'llm','seed':42,'step_mode':False}).json()
        save('project',project)
        response=c.post(f"/api/v1/projects/{project['id']}/delivery",headers={'Idempotency-Key':'real-ticketing-two-changes'})
    response.raise_for_status();run=response.json()['run_id'];prefix=f'/api/v1/runs/{run}'
    status=c.get(prefix+'/delivery').json();save('status',status)
    for key,path in [('traces','/traces'),('artifacts','/artifacts'),('baselines','/baselines'),('changes','/changes'),('simulation','/simulation'),('report','/simulation/report')]:
        r=c.get(prefix+path);save(key,r.json())
    with app.state.runtime.sessions() as session:
        save('events',[{'sequence':e.sequence,'kind':e.kind,'payload':e.payload} for e in session.scalars(select(Event).where(Event.run_id==run).order_by(Event.sequence))])
        save('approvals',[{'id':a.id,'target_id':a.target_id,'target_version':a.target_version,'status':a.status,'decision':a.decision} for a in session.scalars(select(Approval).where(Approval.run_id==run))])
    bases=c.get(prefix+'/baselines').json()
    for base in bases:
        r=c.get(prefix+f"/export?baseline_version={base['version']}")
        if r.status_code==200:(out/f"plan-v{base['version']}.xml").write_bytes(r.content)
    changes=c.get(prefix+'/changes').json()
    ok=status['status']=='completed' and len(changes)==2 and all(x['status']=='applied' for x in changes) and len(bases)==3
    save('manifest',{'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'run_id':run,'model':provider.model,'provider':provider.name,'real_api_calls':provider.calls,'success':ok,'execution_mode':'simulation','note':'API调用真实；开发和测试成果为模拟；无Mock回退。'})
    print('FINAL',status,'calls',provider.calls,'changes',len(changes),'baselines',len(bases),flush=True)
    if not ok:raise SystemExit(1)
