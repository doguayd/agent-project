from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    SUPERVISOR = "supervisor"
    CODER      = "coder"
    REVIEWER   = "reviewer"
    TESTER     = "tester"
    RESEARCHER = "researcher"
    DEBUGGER   = "debugger"
    FAST       = "fast"


class TaskStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


class Task(BaseModel):
    id:             str
    type:           AgentType
    description:    str
    context:        str        = ""
    dependencies:   list[str]  = Field(default_factory=list)
    parallel_group: int        = 0          # Aynı gruptakiler eş zamanlı çalışır
    model_override: Optional[str] = None    # "provider:model" — supervisor seçebilir
    status:         TaskStatus = TaskStatus.PENDING
    result:         Optional[str] = None
    error:          Optional[str] = None
    created_at:     datetime   = Field(default_factory=datetime.now)
    completed_at:   Optional[datetime] = None


class ExecutionPlan(BaseModel):
    goal:             str
    analysis:         str        = ""
    tasks:            list[Task] = Field(default_factory=list)
    total_groups:     int        = 0
    estimated_agents: int        = 0


class AgentResult(BaseModel):
    task_id:     str
    agent_type:  AgentType
    success:     bool
    output:      str
    errors:      list[str]       = Field(default_factory=list)
    metadata:    dict[str, Any]  = Field(default_factory=dict)
    duration_s:  float           = 0.0
    saved_files: list[str]       = Field(default_factory=list)


class Message(BaseModel):
    role:      str              # "system" | "user" | "assistant"
    content:   str
    agent:     Optional[str]   = None
    timestamp: datetime        = Field(default_factory=datetime.now)


class SystemState(BaseModel):
    """Tüm oturum boyunca tutulan global durum."""
    session_id:   str
    goal:         str        = ""
    iteration:    int        = 0
    plan:         Optional[ExecutionPlan] = None
    results:      dict[str, AgentResult] = Field(default_factory=dict)
    final_review: str        = ""
    started_at:   datetime   = Field(default_factory=datetime.now)
