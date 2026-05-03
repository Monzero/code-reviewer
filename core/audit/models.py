from __future__ import annotations
from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field
import uuid


class LLMMeta(BaseModel):
    provider: str
    model: str
    model_version: str


class TokenUsage(BaseModel):
    input: int
    output: int


class AgentResultOk(BaseModel):
    status: Literal["ok"] = "ok"
    score: float
    reasoning: str
    confidence: Literal["low", "medium", "high"]
    llm: LLMMeta
    prompt_version: str
    tokens: TokenUsage
    latency_ms: int
    raw_llm_response: str


class SubScore(BaseModel):
    score: float
    reasoning: str


class CodeAgentResultOk(AgentResultOk):
    sub_scores: dict[str, SubScore]


class AgentResultFailed(BaseModel):
    status: Literal["failed"] = "failed"
    error: str


FlatAgentResult = Annotated[
    Union[AgentResultOk, AgentResultFailed],
    Field(discriminator="status"),
]

CodeAgentResult = Annotated[
    Union[CodeAgentResultOk, AgentResultFailed],
    Field(discriminator="status"),
]


class KeyDecision(BaseModel):
    decision: str
    ownership_signal: str
    question: str


class OwnershipAgentResultOk(AgentResultOk):
    key_decisions: list[KeyDecision]


OwnershipAgentResult = Annotated[
    Union[OwnershipAgentResultOk, AgentResultFailed],
    Field(discriminator="status"),
]


class AgentResults(BaseModel):
    objective: FlatAgentResult
    code: CodeAgentResult
    ui: FlatAgentResult
    ownership: OwnershipAgentResult | None = None


class JudgeOverride(BaseModel):
    agent: str
    original_score: float
    override_score: float
    reason: str
    overridden_by: str
    overridden_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class AggregatedResult(BaseModel):
    overall_score: float | None
    objective_score: float | None
    code_score: float | None
    ui_score: float | None
    ownership_score: float | None = None
    weights_used: dict[str, float]
    summary: str
    flags: list[str]


class InputSnapshot(BaseModel):
    project_name: str
    participant: str
    objective: str
    repo_url: str
    repo_commit_sha: str
    ui_url: str


class EvaluationRecord(BaseModel):
    evaluation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    triggered_by: str
    system_version: str = "1.0.0"
    re_evaluated_from: str | None = None
    input_snapshot: InputSnapshot
    config_snapshot: dict
    agents: AgentResults
    aggregated: AggregatedResult
    judge_notes: str = ""
