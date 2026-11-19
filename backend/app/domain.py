from enum import StrEnum


class Role(StrEnum):
    SPONSOR = "sponsor"
    PROJECT_MANAGER = "project_manager"
    REQUIREMENTS_ANALYST = "requirements_analyst"
    DEVELOPER = "developer"
    TESTER = "tester"
    PROGRESS_COST_ANALYST = "progress_cost_analyst"


class SponsorMode(StrEnum):
    HUMAN = "human"
    LLM = "llm"


class LLMMode(StrEnum):
    MOCK = "mock"
    REAL = "real"


class Phase(StrEnum):
    INITIATING = "initiating"
    PLANNING = "planning"
    EXECUTING = "executing"
    MONITORING_CONTROLLING = "monitoring_controlling"
    CLOSING = "closing"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
