"""Stage 5 review API: paged failures, suggestions, and the action log.

GET  /failures?rule=&company=&cursor=&limit=100
GET  /loans/{loan_id}/suggestion
POST /loans/{loan_id}/action
"""
from __future__ import annotations

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from src.api.db import get_connection
from src.api.review import NotFoundError, get_suggestion, list_failures, record_action
from src.api.schemas import (
    ActionRequest,
    ActionResponse,
    FailuresPage,
    SuggestionResponse,
)

app = FastAPI(title="LoanShield Review API")

# Local dev only: frontend runs on a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


def db_conn():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@app.get("/failures", response_model=FailuresPage)
def get_failures(
    rule: int | None = Query(default=None, ge=1, le=3),
    company: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    conn=Depends(db_conn),
):
    rows, next_cursor = list_failures(conn, rule, company, cursor, limit)
    return {"items": rows, "next_cursor": next_cursor}


@app.get("/loans/{loan_id}/suggestion", response_model=SuggestionResponse)
def get_loan_suggestion(loan_id: str, conn=Depends(db_conn)):
    try:
        return get_suggestion(conn, loan_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/loans/{loan_id}/action", response_model=ActionResponse)
def post_loan_action(loan_id: str, body: ActionRequest, conn=Depends(db_conn)):
    try:
        return record_action(conn, loan_id, body.action, body.payload, body.actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OPA revalidation failed: {exc}") from exc
