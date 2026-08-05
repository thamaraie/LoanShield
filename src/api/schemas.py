"""Pydantic request/response models for the Stage 5 review API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class FailureRow(BaseModel):
    loan_id: str
    company_name: str
    hq_country: str
    asset_description: str
    asset_owner: str
    loan_value: float
    loan_value_eur: float
    loan_currency: str
    expected_currency: str
    asset_value: float
    rule1_pass: bool
    rule2_pass: bool
    rule3_pass: bool
    fx_rate_used: Optional[float] = None
    fx_fetched_at: Optional[str] = None
    degraded: bool
    policy_version: str
    current_state: Optional[str] = None


class FailuresPage(BaseModel):
    items: list[FailureRow]
    next_cursor: Optional[str] = None


class ReviewStatus(BaseModel):
    manual_fix: int
    accept_ai: int
    ignore: int
    unresolved: int
    still_failing: int


class CompanyTotal(BaseModel):
    company_name: str
    loan_value_eur: float


class RunMetadata(BaseModel):
    timestamp: Optional[str] = None
    fx_rates: dict[str, float] = {}
    fx_degraded: bool
    policy_version: Optional[str] = None


class ReportResponse(BaseModel):
    total_checked: int
    rule1_failures: int
    rule2_failures: int
    rule3_failures: int
    failed_any: int
    review_status: ReviewStatus
    per_company: list[CompanyTotal]
    run: RunMetadata


class SuggestionResponse(BaseModel):
    loan_id: str
    rule: Literal[1, 2, 3]
    action: str
    explanation: str
    source_page: Optional[int] = None
    asset_name: Optional[str] = None
    verified: bool
    cache_hit: bool


class ActionRequest(BaseModel):
    action: Literal["manual_fix", "ignore", "accept_ai"]
    payload: dict[str, Any] = {}
    actor: str


class ActionResponse(BaseModel):
    loan_id: str
    action: str
    created_at: datetime
    still_failing: Optional[bool] = None
