from fastapi import APIRouter,BackgroundTasks,Header,HTTPException
from sqlalchemy import select
from ..models import Approval,Artifact,NodeReceipt,Project,Run


def delivery_router(runtime):
    router=APIRouter(prefix='/api/v1')

    def execute(run_id):
        with runtime.lock:
            runtime.delivery.drive(run_id)

    def load(session,run_id):
        run=session.get(Run,run_id)
        marker=session.scalar(select(NodeReceipt).where(NodeReceipt.run_id==run_id,NodeReceipt.node=='delivery_command'))
        if not run or not marker:
            raise HTTPException(404,'Delivery run not found')
        return run

    @router.post('/projects/{project_id}/delivery',status_code=202)
    def start(project_id: str,background: BackgroundTasks,idempotency_key: str=Header(min_length=1,max_length=80)):
        with runtime.lock,runtime.sessions.begin() as session:
            if not session.get(Project,project_id):
                raise HTTPException(404,'Project not found')
            existing=session.scalar(select(Run).where(Run.project_id==project_id,Run.request_key==f'delivery:{idempotency_key}'))
            if existing:
                return {'run_id':existing.id,'status':existing.status}
            if session.scalar(select(Run).where(Run.project_id==project_id)):
                raise HTTPException(409,'Project already has a run; resume it or create a new project')
            run=Run(project_id=project_id,request_key=f'delivery:{idempotency_key}')
            session.add(run)
            session.flush()
            session.add(NodeReceipt(run_id=run.id,node='delivery_command',patch={'project_id':project_id,'idempotency_key':idempotency_key}))
            run_id=run.id
        background.add_task(execute,run_id)
        return {'run_id':run_id,'status':'ready'}

    @router.get('/runs/{run_id}/delivery')
    def status(run_id: str):
        with runtime.sessions() as session:
            run=load(session,run_id)
            state=runtime.delivery.graph.get_state(runtime.delivery.config(run_id))
            paused=any(task.interrupts for task in state.tasks)
            failed=bool(run.error) or any(task.error for task in state.tasks)
            result='failed' if failed else (('waiting_step' if state.values.get('phase')=='waiting_step' else 'waiting_approval') if paused
                else ('running' if state.next else state.values.get('phase','ready')))
            pending=session.scalars(select(Approval).where(Approval.run_id==run_id,Approval.status.in_(['pending','failed']))).all()
            return {'run_id':run_id,'project_id':run.project_id,'status':result,'phase':state.values.get('phase','initiating'),'error':run.error,
                    'execution_mode':'simulation','pending_approvals':[{'id':a.id,'target_id':a.target_id,'target_version':a.target_version,
                        'kind':session.get(Artifact,a.target_id).kind,'status':a.status} for a in pending]}

    @router.post('/runs/{run_id}/delivery/resume',status_code=202)
    def resume(run_id: str,background: BackgroundTasks):
        with runtime.lock,runtime.sessions() as session:
            run=load(session,run_id)
            state=runtime.delivery.graph.get_state(runtime.delivery.config(run_id))
            if not state.next and state.values:
                raise HTTPException(409,'Delivery is already terminal')
            project=session.get(Project,run.project_id)
            pending=session.scalars(select(Approval).where(Approval.run_id==run_id,Approval.status=='pending')).all()
            if project.sponsor_mode.value=='human' and any(approval.decision is None for approval in pending):
                raise HTTPException(409,'Submit pending Sponsor decisions first')
        background.add_task(execute,run_id)
        return {'run_id':run_id,'status':'ready'}

    @router.get('/runs/{run_id}/artifacts')
    def artifacts(run_id: str):
        with runtime.sessions() as session:
            run=session.get(Run,run_id)
            if not run:
                raise HTTPException(404,'Run not found')
            return [{'id':a.id,'kind':a.kind,'version':a.version,'author':a.author,'payload':a.payload}
                    for a in session.scalars(select(Artifact).where(Artifact.project_id==run.project_id).order_by(Artifact.kind,Artifact.version))]

    return router
