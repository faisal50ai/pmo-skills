"""Versioned contracts for a narrow, tool-free instruction-ablation study."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import Contract, Evidence, Identifier, Text

Condition = Literal["baseline", "skill"]
NonNegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]


class Question(Contract):
    id: Identifier
    question: Text


class Case(Contract):
    id: Identifier
    skill: Literal["pmo-raid", "pmo-status"]
    sources: dict[str, Text]
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Case:
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("Duplicate question IDs")
        if not self.sources:
            raise ValueError("Sources required")
        return self


class Answer(Contract):
    id: str
    value: str | None
    evidence: list[Evidence]


class ProbeOutput(Contract):
    answers: list[Answer]


class Config(Contract):
    model: Text
    repeats: Annotated[int, Field(strict=True, ge=1, le=20)] = 3
    seed: int = 41
    max_output_tokens: Annotated[int, Field(strict=True, ge=128, le=16000)] = 1000
    max_requests: Annotated[int, Field(strict=True, ge=2, le=1000)] = 60
    max_cost_usd: Positive
    input_per_million: Positive
    output_per_million: Positive
    pricing_reference: Text
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 60


class Request(Contract):
    id: Identifier
    case_id: Identifier
    condition: Condition
    repeat: Annotated[int, Field(strict=True, ge=1)]
    instructions: str
    input: str
    reserved_usd: NonNegative


class Manifest(Contract):
    protocol: Literal["pmo-instruction-probe-v1"] = "pmo-instruction-probe-v1"
    config: Config
    dataset_sha256: str
    labels_sha256: str
    skills_sha256: str
    schema_sha256: str
    requests_sha256: str
    planned_requests: Count
    estimated_reserve_usd: NonNegative
    sdk_version: str
    created_at: str


class Outcome(Contract):
    id: Identifier
    status: Literal["completed", "refused", "incomplete", "invalid_output", "api_error", "skipped"]
    actual_model: str | None = None
    response_id: str | None = None
    output: ProbeOutput | None = None
    output_text: str | None = None
    latency_ms: NonNegative | None = None
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    cached_input_tokens: Count | None = None
    estimated_cost_usd: NonNegative | None = None
    error_type: str | None = None


class Judgment(Contract):
    id: Identifier
    support: Literal["supported", "unsupported", "unclear"]
    reason: Text


class Annotation(Contract):
    review_id: Identifier
    reviewer: Text
    judgments: list[Judgment]
