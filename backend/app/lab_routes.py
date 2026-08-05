"""Config-gated lab routes for the induced migration incident.

The hot-write route is not a general application write API. B3's controller
uses it to create a measured distinction between requests queued in the app's
pool and requests that reached PostgreSQL and are blocked by the backfill.

HC-1: pool checkout and statement execution need independent timeouts. A
checkout timeout alone does not bound a query that already owns a connection.

HC-2: both SET LOCAL statements and the UPDATE must share one explicit
transaction on one pooled connection. Pool connections use autocommit, so a
bare SET LOCAL would reset before the UPDATE.
"""

from __future__ import annotations

import time
from typing import Literal

import psycopg
import psycopg_pool
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from psycopg import sql

from . import db as app_db
from .config import get_settings


router = APIRouter()


class HotWriteRequest(BaseModel):
    order_id: int


class HotWriteResult(BaseModel):
    order_id: int
    outcome: Literal["committed", "statement_timeout", "pool_timeout"]
    waited_seconds: float


def _require_lab_endpoints() -> None:
    settings = get_settings()
    if not settings.lab_endpoints_enabled:
        raise HTTPException(
            status_code=404,
            detail="lab endpoints are disabled; set LAB_ENDPOINTS_ENABLED=1",
        )
    if settings.db_pool_min_size != settings.db_pool_max_size:
        raise HTTPException(
            status_code=503,
            detail=(
                "lab endpoints require DB_POOL_MIN_SIZE to equal "
                "DB_POOL_MAX_SIZE so every pool slot is open before "
                "the hot-write requests start"
            ),
        )


@router.post("/v1/lab/hot-write", response_model=HotWriteResult)
def _hot_write(request: HotWriteRequest) -> HotWriteResult:
    """Run one tagged write through the real application pool."""
    _require_lab_endpoints()
    settings = get_settings()
    started = time.monotonic()
    pool = app_db.get_pool()
    try:
        with pool.connection(timeout=settings.lab_hot_write_checkout_timeout_seconds) as conn:
            # HC-2: keep the transaction-local settings and the write together.
            with conn.transaction():
                conn.execute(
                    "SET LOCAL application_name = 'workbench-lab-api-hot-write'"
                )
                # HC-1: this bounds a lock wait after checkout; the checkout
                # timeout above separately bounds waiting for a pool slot.
                conn.execute(
                    sql.SQL("SET LOCAL statement_timeout = {}").format(
                        sql.Literal(
                            settings.lab_hot_write_statement_timeout
                        )
                    )
                )
                conn.execute(
                    "UPDATE workbench_lab.orders SET status = 'touched' "
                    "WHERE order_id = %s",
                    (request.order_id,),
                )
    except psycopg_pool.PoolTimeout:
        return HotWriteResult(
            order_id=request.order_id,
            outcome="pool_timeout",
            waited_seconds=time.monotonic() - started,
        )
    except psycopg.errors.QueryCanceled:
        return HotWriteResult(
            order_id=request.order_id,
            outcome="statement_timeout",
            waited_seconds=time.monotonic() - started,
        )
    return HotWriteResult(
        order_id=request.order_id,
        outcome="committed",
        waited_seconds=time.monotonic() - started,
    )


@router.get("/v1/lab/pool-status")
def _pool_status() -> dict[str, float | int]:
    """Return pool-native counters without taking a connection for the request."""
    _require_lab_endpoints()
    # Calling connection() here would use a scarce slot and wait during the
    # condition we need to observe. get_stats() reads the pool counters directly.
    stats = app_db.get_pool().get_stats()
    return {
        "pool_size": stats.get("pool_size", 0),
        "pool_available": stats.get("pool_available", 0),
        "requests_waiting": stats.get("requests_waiting", 0),
        "requests_queued": stats.get("requests_queued", 0),
        "usage_ms": stats.get("usage_ms", 0),
    }
