from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    name: str
    website: str | None = None
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Launch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    company_id: int
    source: str
    source_id: str
    title: str
    url: str | None = None
    posted_at: datetime
    engagement_score: float = 0.0
    engagement_breakdown: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class FundingRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    company_id: int
    source: str
    source_id: str
    amount_usd: int | None = None
    round_type: str | None = None
    announced_at: datetime
    investors: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    company_id: int
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    x_handle: str | None = None
    confidence: float = 0.0
    source: str


class DmDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    launch_id: int
    subject: str
    body: str
    tone: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    prompt_version: str
