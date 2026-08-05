"""Pydantic request/response models for the Stage 5 review API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class FailureRow(BaseModel):
    loan_id: str
    company_id: str
    company_name: str
    loan_value: float
    loan_value_eur: float
    loan_currency: str
    expected_currency: str
    asset_value: float
    rule1_pass: bool
    rule2_pass: bool
    rule3_pass: bool
    fx_rate_used: float
    fx_fetched_at: datetime
    policy_version: str
    current_state: Optional[str] = None


class FailuresPage(BaseModel):
    items: list[FailureRow]
    next_cursor: Optional[str] = None


class SuggestionResponse(BaseModel):
    loan_id: str
    rule: Literal[1, 2, 3]
    suggestion_type: str
    detail: dict[str, Any]
    revalidated: bool
    source: Literal["cache", "generated"]


class ActionRequest(BaseModel):
    action: Literal["manual_fix", "ignore", "accept_ai"]
    payload: dict[str, Any] = {}
    actor: str


class ActionResponse(BaseModel):
    loan_id: str
    action: str
    created_at: datetime
    still_failing: Optional[bool] = None
