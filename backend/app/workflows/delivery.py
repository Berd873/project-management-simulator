"""Top-level LangGraph coordinates requirements through final acceptance."""
from typing import TypedDict
from langgraph.graph import END,START,StateGraph
from langgraph.types import Command,interrupt
from sqlalchemy import func,select
from ..domain import Role
from ..models import Approval,Artifact,NodeReceipt,Project,Run,SimulationRun
from ..services.plan_builder import build_plan
from ..services.planning import Plan,cpm
from ..services.simulation import Scenario
from .execution_agents import call_role
from .simulation import json_value


class DeliveryState(TypedDict,total=False):
    run_id: str
    phase: str
    plan_artifact_id: str
    plan_approval_id: str
    srs_artifact_id: str
    estimate_artifact_id: str


class DeliveryWorkflow:
    def __init__(self,runtime,saver):
        self.runtime=runtime
        graph=StateGraph(DeliveryState)
        graph.add_node('initiate',self.initiate)
        graph.add_node('wait_charter',self.wait)
        graph.add_node('build_plan',self.plan)
        graph.add_node('approve_plan',self.approve)
        graph.add_node('wait_plan',self.wait)
        graph.add_node('execute',self.execute)
        graph.add_node('wait_execution',self.wait)
        graph.add_edge(START,'initiate')
        graph.add_conditional_edges('initiate',lambda s:'wait_charter' if s['phase']=='waiting_approval' else ('build_plan' if s['phase']=='awaiting_m3' else END))
        graph.add_edge('wait_charter','initiate')
        graph.add_edge('build_plan','approve_plan')
        graph.add_conditional_edges('approve_plan',lambda s:'execute' if s['phase']=='plan_approved' else ('wait_plan' if s['phase']=='waiting_approval' else END))
        graph.add_edge('wait_plan','approve_plan')
        graph.add_conditional_edges('execute',lambda s:'wait_execution' if s['phase'] in ['waiting_change','waiting_acceptance','waiting_step'] else END)
        graph.add_edge('wait_execution','execute')
        self.graph=graph.compile(checkpointer=saver)

    @staticmethod
    def config(run_id):
        return {'configurable':{'thread_id':f'{run_id}:delivery:v1'},'recursion_limit':1000}

    def wait(self,state):
        interrupt({'run_id':state['run_id'],'phase':state['phase']})
        return {}

    def initiate(self,state):
        self.runtime.drive(state['run_id'])
        with self.runtime.sessions() as session:
            run=session.get(Run,state['run_id'])
            if run.status=='failed':
                raise ValueError('Role proposal workflow failed')
            return {'phase':run.status}

    def plan(self,state):
        cached=self.runtime.receipt(state,'delivery_build_plan')
        if cached is not None:
            return cached
        original=self.runtime.graph.get_state(self.runtime.config(state['run_id'])).values
        srs_id=original['artifact_refs'][Role.REQUIREMENTS_ANALYST.value]
        with self.runtime.sessions() as session:
            wbs=session.get(Artifact,srs_id).payload
            run=session.get(Run,state['run_id'])
            project_id=run.project_id
        estimates=call_role(self.runtime,state['run_id'],0,Role.PROGRESS_COST_ANALYST,'estimate_plan',{'wbs':wbs})
        plan=build_plan(wbs,estimates.payload)
        with self.runtime.sessions.begin() as session:
            estimate_version=(session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==project_id,Artifact.kind=='planning_estimates')) or 0)+1
            estimate=Artifact(project_id=project_id,kind='planning_estimates',version=estimate_version,author=Role.PROGRESS_COST_ANALYST,payload=estimates.payload)
            session.add(estimate)
            version=(session.scalar(select(func.max(Artifact.version)).where(Artifact.project_id==project_id,Artifact.kind=='plan')) or 0)+1
            artifact=Artifact(project_id=project_id,kind='plan',version=version,author=Role.PROGRESS_COST_ANALYST,payload=plan.model_dump(mode='json'))
            session.add(artifact)
            session.flush()
            approval=Approval(run_id=state['run_id'],target_id=artifact.id,target_version=version)
            session.add(approval)
            session.flush()
            inputs={'run_id':state['run_id'],'project_id':project_id,'approval_id':approval.id,'artifact_id':artifact.id,'change_id':None,'effective_day':0}
            session.add(NodeReceipt(run_id=state['run_id'],node=f'plan_approval_input:{approval.id}',patch=inputs))
            return self.runtime.save(session,state,'delivery_build_plan',{'plan_artifact_id':artifact.id,'plan_approval_id':approval.id,
                'srs_artifact_id':srs_id,'estimate_artifact_id':estimate.id})

    def approve(self,state):
        self.runtime.plan_approval.drive(state['run_id'],state['plan_approval_id'])
        with self.runtime.sessions() as session:
            status=session.get(Approval,state['plan_approval_id']).status
        if status=='failed':
            raise ValueError('Plan approval failed')
        return {'phase':'plan_approved' if status=='approve' else ('rejected' if status=='reject' else 'waiting_approval')}

    def execute(self,state):
        with self.runtime.sessions.begin() as session:
            row=session.get(SimulationRun,state['run_id'])
            if not row:
                artifact=session.get(Artifact,state['plan_artifact_id'])
                plan=Plan.model_validate(artifact.payload)
                run=session.get(Run,state['run_id'])
                ids={task.id for task in plan.tasks}
                project=session.get(Project,run.project_id)
                scenario=Scenario(version='generated-v2',forced_first_test_failures=['3' if '3' in ids else sorted(ids)[0]],
                    change_trigger_day=3,formal_management=True,final_acceptance=True,step_mode=project.step_mode,
                    change_description=('Add booking cancellation notifications' if any(word in project.description.lower() for word in ['booking','预约'])
                        else 'Add overdue reminders' if any(word in project.description.lower() for word in ['library','图书'])
                        else 'Add an acceptance review checklist'))
                if any(word in project.description.lower() for word in ['ticketing', '校园活动票务']):
                    scenario=Scenario(version='campus-ticketing-v1',forced_first_test_failures=[sorted(ids)[-1]],
                        formal_management=True,final_acceptance=True,step_mode=project.step_mode,
                        scheduled_changes=[{'day':1,'description':'CR-01: 新增活动取消后的退款申请与审批记录；仅模拟退款，不连接真实支付。新增任务必须使用全新 ID，保留现有任务及依赖。'},
                            {'day':2,'description':'CR-02: 新增离线验票及重复核销防护，网络恢复后同步核销记录；仅模拟。新增任务必须使用全新 ID，不修改现有任务及依赖。'}])
                session.add(SimulationRun(run_id=run.id,plan=plan.model_dump(mode='json'),scenario=scenario.model_dump(mode='json'),
                    seed=session.get(Project,run.project_id).seed,schedule=json_value(cpm(plan))))
        self.runtime.simulation.drive(state['run_id'])
        with self.runtime.sessions() as session:
            status=session.get(SimulationRun,state['run_id']).status
        if status=='failed':
            raise ValueError('Managed simulation failed')
        return {'phase':status}

    def drive(self,run_id):
        config=self.config(run_id)
        state=self.graph.get_state(config)
        value=Command(resume=True) if any(task.interrupts for task in state.tasks) else (None if state.values else {'run_id':run_id})
        try:
            self.graph.invoke(value,config)
            with self.runtime.sessions.begin() as session:
                session.get(Run,run_id).error=None
        except Exception as exc:
            with self.runtime.sessions.begin() as session:
                session.get(Run,run_id).error=type(exc).__name__
                self.runtime.emit(session,run_id,'delivery_failed',{'error':type(exc).__name__})
