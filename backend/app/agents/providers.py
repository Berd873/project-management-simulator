import json
import os
from typing import Protocol
import httpx
from .contracts import AgentContext, ApprovalDecision, DecisionEnvelope, output_schema
from ..domain import Role


class Provider(Protocol):
    name: str
    def generate(self, context: AgentContext) -> dict: ...
    def approve(self, target: dict, charter: dict) -> dict: ...


class MockProvider:
    name = "mock:v6"
    prompt_version = 'mock-decisions-v6'

    def approve(self, target, charter):
        evidence = 'final simulated acceptance' if 'final_metrics' in charter else 'reviewed proposal'
        return {**target, 'decision': 'approve', 'reason': f'Mock Sponsor approves {evidence} evidence'}

    def generate(self, context):
        if context.operation != 'proposal':
            if context.operation=='monitor':
                metrics=context.facts['metrics']
                network=context.facts.get('cpm',{})
                risks=[]
                if metrics['sv_cents']<0:
                    risks.append('进度落后于批准计划；检查关键任务、资源等待与剩余依赖。')
                if metrics['cv_cents']<0:
                    risks.append('模拟成本高于已完成工作的挣值；复核返工原因和剩余成本预测。')
                if not risks:
                    risks.append('当前偏差未显示落后或成本低效，仍需监控后续资源与缺陷风险。')
                assessment=(f"第 {metrics['status_day']} 日：SPI={metrics['spi'] if metrics['spi'] is not None else '未定义'}，"
                    f"CPI={metrics['cpi'] if metrics['cpi'] is not None else '未定义'}；"
                    f"SV={metrics['sv_cents']} 分，CV={metrics['cv_cents']} 分。"
                    f"零浮时关键任务：{', '.join(network.get('critical_task_ids',[])) or '无'}；"
                    f"CPM 网络工期 {network.get('duration_days','—')} 日，不含资源等待。")
                return {'role':context.role.value,'rationale':'解释 Python 服务提供的指标和关键路径，不重算或覆盖数值',
                        'payload':{'assessment':assessment,'risks':risks}}
            if context.operation=='estimate_plan':
                durations={'1':2,'2':1,'3':2,'4':1}
                return {'role':context.role.value,'rationale':'Estimate effort and resource rates; Python computes costs',
                    'payload':{'resources':[{'id':'developer','capacity':1,'rate_cents_per_day':5000}],
                    'tasks':[{'task_id':task['id'],'duration_days':durations.get(task['id'],2),'resource_id':'developer'} for task in context.facts['wbs']['tasks']],
                    'assumptions':['One full-time developer; one work unit per day; CNY integer cents']}}
            if context.operation=='propose_change':
                plan=context.facts['current_plan']
                has_successor={edge['predecessor'] for edge in plan['dependencies']}
                return {'role':context.role.value,'rationale':'Propose a scoped response to the requested enhancement',
                    'payload':{'reason':'Add overdue reminders requested during monitoring',
                    'added_tasks':[{'id':'change.overdue_reminders','title':'Overdue reminders','duration_days':2,
                    'resource_id':plan['resources'][0]['id'],'acceptance_criteria':['Simulated overdue reader receives a reminder'],
                    'predecessor_ids':[task['id'] for task in plan['tasks'] if task['id'] not in has_successor]}]}}
            operations = {
                'dispatch':{'task_ids':context.facts.get('suggested_task_ids',[]),'summary':'Assign eligible simulated work within available resource capacity'},
                'execute':{'actions':context.facts.get('expected_actions',[]),'approach':'Execute assigned simulated work; repair known defects first'},
                'test_results':{'results':context.facts.get('expected_results',[]),'summary':'Simulated tests checked against engine evidence'},
                'monitor':{'assessment':'Interpret deterministic metrics; no numeric override','risks':['Resource waiting and rework may affect completion']},
                'close':{'recommendation':'request_acceptance','summary':'All simulated scope is accepted; request Sponsor final review'},
            }
            return {'role':context.role.value,'rationale':'Evidence-based simulated role response','payload':operations[context.operation]}
        ids = [k.removeprefix('task:') for k in context.artifact_refs if k.startswith('task:')]
        payloads = {
            Role.SPONSOR: {"requirements": [context.brief]},
            Role.PROJECT_MANAGER: {"objectives": [context.brief], "success_criteria": ["Sponsor validates agreed scope"],
                "constraints": ["Simulation only; no actual source code execution", "Scope, schedule and cost baselines require formal approval"],
                "stakeholders": ["Sponsor", "Project Manager", "Requirements Analyst", "Developer", "Tester", "Progress & Cost Analyst"]},
            Role.REQUIREMENTS_ANALYST: {"in_scope": [context.brief], "out_scope": ["Real source code execution"],
                                      "tasks": [{"id": "1.1", "title": "Deliver agreed requirements", "acceptance_criteria": ["Scope covered"]}]},
            Role.PROGRESS_COST_ANALYST: {"assumptions": ["Initial aggregate proposal; per-task resource estimates are required before plan approval"], "suggested_duration_days": 5, "suggested_budget_cents": 100000},
            Role.DEVELOPER: {"task_ids": ids, "approach": "Prepare simulated implementation proposal"},
            Role.TESTER: {"task_ids": ids, "cases": ["Verify agreed acceptance criteria in future simulation"]},
        }
        if context.role==Role.REQUIREMENTS_ANALYST and any(word in context.brief.lower() for word in ['library','图书']):
            payloads[context.role]={'in_scope':['Catalog management','Reader management','Borrowing and returns','Catalog search'],
                'out_scope':['Real source code execution'], 'tasks':[
                {'id':'1','title':'Catalog management','acceptance_criteria':['Catalog entries can be created and updated'],'predecessor_ids':[]},
                {'id':'2','title':'Reader management','acceptance_criteria':['Reader records can be maintained'],'predecessor_ids':[]},
                {'id':'3','title':'Borrowing and returns','acceptance_criteria':['Borrowed items can be returned'],'predecessor_ids':['1','2']},
                {'id':'4','title':'Catalog search','acceptance_criteria':['Catalog items can be located'],'predecessor_ids':['1']}]}
        return {"role": context.role.value, "rationale": "Versioned deterministic mock decision", "payload": payloads[context.role]}


class RealProvider:
    """Configurable OpenAI-compatible JSON chat endpoint; never falls back to mock."""
    prompt_version = 'role-json-v3'
    def __init__(self):
        self.model = os.getenv("LLM_MODEL", "")
        self.key = os.getenv("LLM_API_KEY", "")
        self.base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip('/')
        self.timeout = float(os.getenv('LLM_TIMEOUT_SECONDS', '30'))
        if not 0 < self.timeout <= 120:
            raise ValueError('LLM_TIMEOUT_SECONDS must be between zero and 120')
        if not self.model or not self.key:
            raise ValueError("LLM_MODEL and LLM_API_KEY are required")
        self.name = f"real:{self.model}"

    def generate(self, context):
        schema = DecisionEnvelope.model_json_schema()
        payload_schema = output_schema(context).model_json_schema()
        schema.setdefault('$defs', {}).update(payload_schema.pop('$defs', {}))
        schema['properties']['payload'] = payload_schema
        schema['properties']['role'] = {'const': context.role.value, 'type': 'string'}
        return self.request(schema, context.model_dump_json())

    def approve(self, target, charter):
        return self.request(ApprovalDecision.model_json_schema(), json.dumps({'target': target, 'charter': charter}))

    def request(self, schema, content):
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.base + '/chat/completions', headers={"Authorization": f"Bearer {self.key}"}, json={
                "model": self.model, "response_format": {"type": "json_object"}, "max_tokens": 2048,
                "messages": [{"role": "system", "content": "Act only as the specified project role. Return exactly one JSON object matching this JSON Schema. Do not wrap it in schema, envelope, or result keys. " + json.dumps(schema)},
                             {"role": "user", "content": content}],
            })
            response.raise_for_status()
            return json.loads(response.json()['choices'][0]['message']['content'])
