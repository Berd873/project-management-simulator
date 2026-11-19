from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import LLMMode, Phase, ProjectStatus, SponsorMode


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    sponsor_mode: SponsorMode = SponsorMode.LLM
    llm_mode: LLMMode = LLMMode.MOCK
    execution_mode: Literal["simulation"] = "simulation"
    seed: int = Field(default=42, ge=0, le=2147483647, strict=True)


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: ProjectStatus
    phase: Phase
    simulation_day: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        # SQLite returns naive datetimes; the storage convention is always UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
