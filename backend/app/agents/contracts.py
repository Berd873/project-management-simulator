from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..domain import Role


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AgentContext(Contract):
    project_id: str
    run_id: str
    role: Role
    brief: str
    artifact_refs: dict[str, str] = Field(default_factory=dict)
    artifacts: dict[str, dict] = Field(default_factory=dict)
    execution_mode: Literal["simulation"] = "simulation"
    operation: Literal['proposal','execute','test_results','monitor','close','estimate_plan','propose_change','dispatch'] = 'proposal'
    facts: dict = Field(default_factory=dict)


class Brief(Contract):
    requirements: list[str] = Field(min_length=1)


class Charter(Contract):
    objectives: list[str] = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
    stakeholders: list[str] = Field(min_length=1)


class WorkItem(Contract):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    predecessor_ids: list[str] = Field(default_factory=list)


class Requirements(Contract):
    in_scope: list[str] = Field(min_length=1)
    out_scope: list[str]
    tasks: list[WorkItem] = Field(min_length=1)


class Estimate(Contract):
    assumptions: list[str] = Field(min_length=1)
    suggested_duration_days: int = Field(gt=0, strict=True)
    suggested_budget_cents: int = Field(ge=0, strict=True)
    status: Literal["proposal_only"] = "proposal_only"


class DevelopmentProposal(Contract):
    task_ids: list[str] = Field(min_length=1)
    approach: str = Field(min_length=1)
    execution_mode: Literal["simulation"] = "simulation"
    status: Literal["not_executed"] = "not_executed"


class TestProposal(Contract):
    task_ids: list[str] = Field(min_length=1)
    cases: list[str] = Field(min_length=1)
    execution_mode: Literal["simulation"] = "simulation"
    status: Literal["not_executed"] = "not_executed"


class ApprovalDecision(Contract):
    target_id: str
    target_version: int = Field(gt=0, strict=True)
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


class DecisionEnvelope(Contract):
    role: Role
    schema_version: Literal[1] = 1
    rationale: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict


OUTPUTS = {Role.SPONSOR: Brief, Role.PROJECT_MANAGER: Charter,
           Role.REQUIREMENTS_ANALYST: Requirements, Role.PROGRESS_COST_ANALYST: Estimate,
           Role.DEVELOPER: DevelopmentProposal, Role.TESTER: TestProposal}


class TaskAction(Contract):
    task_id: str
    action: Literal['develop','repair']


class ExecutionActions(Contract):
    actions: list[TaskAction]
    approach: str = Field(min_length=1)
    execution_mode: Literal['simulation'] = 'simulation'


class TestOutcome(Contract):
    task_id: str
    passed: bool = Field(strict=True)
    attempt: int = Field(gt=0,strict=True)


class ExecutionTestReport(Contract):
    results: list[TestOutcome]
    summary: str = Field(min_length=1)
    execution_mode: Literal['simulation'] = 'simulation'


class PerformanceAnalysis(Contract):
    assessment: str = Field(min_length=1)
    risks: list[str]


class ClosureRecommendation(Contract):
    recommendation: Literal['request_acceptance']
    summary: str = Field(min_length=1)


class TaskEstimate(Contract):
    task_id: str
    duration_days: int = Field(gt=0,strict=True)
    resource_id: str


from ..services.planning import Resource


class PlanningEstimates(Contract):
    resources: list[Resource] = Field(min_length=1)
    tasks: list[TaskEstimate] = Field(min_length=1)
    assumptions: list[str] = Field(min_length=1)


class ChangeWorkItem(WorkItem):
    duration_days: int = Field(gt=0,strict=True)
    resource_id: str


class ChangeRecommendation(Contract):
    reason: str = Field(min_length=1)
    added_tasks: list[ChangeWorkItem] = Field(min_length=1)


class TaskAssignment(Contract):
    task_ids: list[str]
    summary: str = Field(min_length=1)


OPERATIONS = {('execute',Role.DEVELOPER):ExecutionActions,('test_results',Role.TESTER):ExecutionTestReport,
              ('monitor',Role.PROGRESS_COST_ANALYST):PerformanceAnalysis,('close',Role.PROJECT_MANAGER):ClosureRecommendation,
              ('estimate_plan',Role.PROGRESS_COST_ANALYST):PlanningEstimates,('propose_change',Role.PROJECT_MANAGER):ChangeRecommendation,
              ('dispatch',Role.PROJECT_MANAGER):TaskAssignment}


def output_schema(context: AgentContext):
    if context.operation == 'proposal':
        return OUTPUTS[context.role]
    schema = OPERATIONS.get((context.operation,context.role))
    if schema is None:
        raise ValueError('Operation is not allowed for this role')
    return schema


def validate_decision(raw: dict, context: AgentContext):
    decision = DecisionEnvelope.model_validate(raw)
    if decision.role != context.role:
        raise ValueError("Role mismatch")
    payload = output_schema(context).model_validate(decision.payload)
    if isinstance(payload,TaskAssignment):
        eligible=set(context.facts['eligible_task_ids'])
        if len(payload.task_ids)!=len(set(payload.task_ids)) or not set(payload.task_ids)<=eligible or (eligible and not payload.task_ids):
            raise ValueError('PM assignments must use eligible tasks and make progress')
        tasks={task['id']:task for task in context.facts['plan']['tasks']}
        capacities={resource['id']:resource['capacity'] for resource in context.facts['plan']['resources']}
        for key in payload.task_ids:
            resource=tasks[key]['resource_id']
            capacities[resource]-=1
            if capacities[resource]<0:
                raise ValueError('PM assignments exceed resource capacity')
    if isinstance(payload,ExecutionActions):
        actual = [a.model_dump() for a in payload.actions]
        expected = context.facts['expected_actions']
        if sorted(actual,key=lambda a:a['task_id']) != sorted(expected,key=lambda a:a['task_id']):
            raise ValueError('Developer cannot override authorized tasks or repair requirements')
    if isinstance(payload,ExecutionTestReport):
        actual = [r.model_dump() for r in payload.results]
        expected = context.facts['expected_results']
        if sorted(actual,key=lambda r:r['task_id']) != sorted(expected,key=lambda r:r['task_id']):
            raise ValueError('Tester cannot contradict deterministic simulated outcomes')
    if isinstance(payload, Requirements):
        ids = [t.id for t in payload.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate WBS task IDs")
        from graphlib import TopologicalSorter
        if any(p not in ids or p==task.id for task in payload.tasks for p in task.predecessor_ids):
            raise ValueError('Unknown or self-dependent WBS task')
        tuple(TopologicalSorter({task.id:set(task.predecessor_ids) for task in payload.tasks}).static_order())
    if isinstance(payload,PlanningEstimates):
        ids=[task.task_id for task in payload.tasks]
        expected={task['id'] for task in context.facts['wbs']['tasks']}
        resource_ids=[resource.id for resource in payload.resources]
        if set(ids)!=expected or len(ids)!=len(expected) or len(set(resource_ids))!=len(resource_ids):
            raise ValueError('Estimates must cover each WBS task exactly once with unique resources')
        if any(task.resource_id not in resource_ids for task in payload.tasks):
            raise ValueError('Estimate references unknown resource')
    if isinstance(payload,ChangeRecommendation):
        ids=[task.id for task in payload.added_tasks]
        old_ids={task['id'] for task in context.facts['current_plan']['tasks']}
        resources={resource['id'] for resource in context.facts['current_plan']['resources']}
        if len(ids)!=len(set(ids)) or set(ids)&old_ids:
            raise ValueError('Change task IDs must be new and unique')
        if any(task.resource_id not in resources or any(p not in old_ids|set(ids) for p in task.predecessor_ids) for task in payload.added_tasks):
            raise ValueError('Change references unknown resource or predecessor')
        from graphlib import TopologicalSorter
        dependencies={key:set() for key in old_ids|set(ids)}
        for edge in context.facts['current_plan']['dependencies']:
            dependencies[edge['successor']].add(edge['predecessor'])
        for task in payload.added_tasks:
            if len(task.predecessor_ids)!=len(set(task.predecessor_ids)):
                raise ValueError('Duplicate change dependencies')
            dependencies[task.id].update(task.predecessor_ids)
        tuple(TopologicalSorter(dependencies).static_order())
    if isinstance(payload, (DevelopmentProposal, TestProposal)):
        allowed = {k.removeprefix('task:') for k in context.artifact_refs if k.startswith('task:')}
        if not set(payload.task_ids) <= allowed:
            raise ValueError("Unknown task reference")
    if not set(decision.evidence_refs) <= set(context.artifact_refs.values()):
        raise ValueError("Unknown evidence reference")
    return decision.model_copy(update={"payload": payload.model_dump(mode="json")})
