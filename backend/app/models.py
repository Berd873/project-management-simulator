from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .domain import LLMMode, Phase, ProjectStatus, Role, SponsorMode


def new_id():
    return str(uuid4())


def utc_now():
    return datetime.now(timezone.utc)


def enum_type(cls):
    return Enum(cls, native_enum=False, create_constraint=True, values_callable=lambda e: [v.value for v in e])


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("seed >= 0"), CheckConstraint("simulation_day >= 0"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    sponsor_mode: Mapped[SponsorMode] = mapped_column(enum_type(SponsorMode), default=SponsorMode.LLM)
    llm_mode: Mapped[LLMMode] = mapped_column(enum_type(LLMMode), default=LLMMode.MOCK)
    execution_mode: Mapped[str] = mapped_column(String(20), default="simulation")
    step_mode: Mapped[bool] = mapped_column(default=False, server_default="0")
    status: Mapped[ProjectStatus] = mapped_column(enum_type(ProjectStatus), default=ProjectStatus.DRAFT)
    phase: Mapped[Phase] = mapped_column(enum_type(Phase), default=Phase.INITIATING)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    simulation_day: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Task(Base):
    """Mutable draft WBS task; approved plans will be immutable snapshots."""
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "wbs_code"),
        CheckConstraint("duration_days > 0"),
        CheckConstraint("budget_cents >= 0"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    wbs_code: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    owner: Mapped[Role] = mapped_column(enum_type(Role))
    duration_days: Mapped[int] = mapped_column(Integer)
    budget_cents: Mapped[int] = mapped_column(Integer)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("project_id", "kind", "version"), CheckConstraint("version > 0"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer, default=1)
    author: Mapped[Role] = mapped_column(enum_type(Role))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("project_id", "request_key"),)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class NodeReceipt(Base):
    __tablename__ = "node_receipts"
    __table_args__ = (UniqueConstraint("run_id", "node"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    node: Mapped[str] = mapped_column(String(100))
    patch: Mapped[dict] = mapped_column(JSON)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (UniqueConstraint("run_id", "node", "attempt"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    node: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(50))
    attempt: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(60),default='legacy-m2-v1',server_default='legacy-m2-v1')
    input_hash: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict] = mapped_column(JSON)
    valid: Mapped[bool]
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("run_id", "target_id", "target_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))
    target_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)


class SimulationRun(Base):
    """Versioned draft plan/scenario; approved baselines are introduced separately in M4."""
    __tablename__ = "simulation_runs"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    plan: Mapped[dict] = mapped_column(JSON)
    scenario: Mapped[dict] = mapped_column(JSON)
    seed: Mapped[int] = mapped_column(Integer)
    schedule: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SimulationTick(Base):
    __tablename__ = "simulation_ticks"
    __table_args__ = (UniqueConstraint("run_id", "day"), CheckConstraint("day >= 0"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.run_id"), index=True)
    day: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    events: Mapped[list] = mapped_column(JSON)
    assignments: Mapped[list] = mapped_column(JSON)


class Baseline(Base):
    __tablename__ = "baselines"
    __table_args__ = (UniqueConstraint('project_id','version'), UniqueConstraint('approval_id'),
                      CheckConstraint('version > 0'), CheckConstraint('effective_day >= 0'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'))
    version: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[str | None] = mapped_column(ForeignKey('baselines.id'), nullable=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey('approvals.id'))
    artifact_id: Mapped[str] = mapped_column(ForeignKey('artifacts.id'))
    effective_day: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    __table_args__ = (UniqueConstraint('run_id','request_key'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), index=True)
    source_baseline_id: Mapped[str] = mapped_column(ForeignKey('baselines.id'))
    artifact_id: Mapped[str] = mapped_column(ForeignKey('artifacts.id'))
    request_key: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    impact: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='proposed')
    applied_baseline_id: Mapped[str | None] = mapped_column(ForeignKey('baselines.id'), nullable=True)
