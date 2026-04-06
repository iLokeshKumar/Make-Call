from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from agents.ism_orchestrator import run_ism_for_company
from database import engine
from models.models import User
from services.campaign_service import run_due_campaign_recipients
from services.dialer_service import run_batch_dialer

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Module-level health state (single source of truth)

_health: dict[str, Any] = {
    "last_cycle_at": None,
    "last_cycle_status": "never",
    "last_cycle_duration_seconds": None,
    "last_cycle_company_count": 0,
    "last_cycle_results": [],
    "total_cycles": 0,
    "total_failed_cycles": 0,
}

_paused: bool = False


def get_worker_health() -> dict[str, Any]:
    """Return a snapshot of the latest worker-cycle health metrics."""
    return {**_health, "paused": _paused}


def pause_worker() -> dict[str, Any]:
    """Pause the automation worker so future cycle invocations are no-ops."""
    global _paused
    _paused = True
    logger.info("[worker] paused by API request")
    return get_worker_health()


def resume_worker() -> dict[str, Any]:
    """Resume the automation worker after a pause."""
    global _paused
    _paused = False
    logger.info("[worker] resumed by API request")
    return get_worker_health()


# Company actor resolution

def get_company_actor_ids(
    session: Session,
    company_id: int | None = None,
) -> dict[int, int]:
    """Return {company_id: first_active_user_id} mapping."""
    query = select(User).where(User.is_active == True)  # noqa: E712
    if company_id is not None:
        query = query.where(User.company_id == company_id)

    users = session.exec(query.order_by(User.company_id.asc(), User.id.asc())).all()
    actors: dict[int, int] = {}
    for user in users:
        actors.setdefault(user.company_id, user.id)
    return actors


# Distributed locking (PostgreSQL advisory locks)

def _acquire_company_lock(session: Session, company_id: int) -> bool:
    """Try to acquire a session-level advisory lock for *company_id*.

    Returns True if the lock was acquired, False if it is already held by
    another worker session (idempotency / distributed-locking guarantee).
    """
    result = session.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": company_id}
    ).scalar()
    return bool(result)


def _release_company_lock(session: Session, company_id: int) -> None:
    """Release the session-level advisory lock for *company_id*."""
    session.execute(
        text("SELECT pg_advisory_unlock(:key)"), {"key": company_id}
    )


# Core worker cycle

def run_worker_cycle(
    session: Session,
    company_id: int | None = None,
    dial_limit_per_company: int = 20,
) -> list[dict[str, Any]]:
    """Run one full worker cycle.

    - Acquires per-company advisory lock  → idempotency / distributed locking.
    - Wraps every company in its own try/except → error isolation.
    - Records per-company and cycle-level metrics → observability.
    """
    if _paused:
        logger.info("[worker] cycle skipped — worker is paused")
        return [{"status": "paused", "message": "Worker is paused. Call /automation/resume to re-enable."}]

    results: list[dict[str, Any]] = []
    cycle_start = datetime.utcnow()
    companies = get_company_actor_ids(session, company_id=company_id)

    logger.info(
        "[worker] cycle started | company_filter=%s | companies=%s",
        company_id,
        list(companies.keys()),
    )

    for target_company_id, actor_user_id in companies.items():
        company_start = datetime.utcnow()
        metric: dict[str, Any] = {
            "company_id": target_company_id,
            "actor_user_id": actor_user_id,
            "status": "skipped",
            "dialer_results": None,
            "campaign_results": None,
            "ism_results": None,
            "error": None,
            "start_at": company_start.isoformat(),
            "end_at": None,
            "duration_seconds": None,
        }

        # Distributed lock
        got_lock = _acquire_company_lock(session, target_company_id)
        if not got_lock:
            logger.warning(
                "[worker] company=%s skipped – lock held by another worker instance",
                target_company_id,
            )
            metric["status"] = "lock_skipped"
            _finalize_metric(metric, company_start)
            results.append(metric)
            continue

        # Per-company work with error isolation
        try:
            # Dialer – isolated: a dialer failure must NOT abort campaign work
            try:
                metric["dialer_results"] = run_batch_dialer(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                    limit=dial_limit_per_company,
                )
                logger.info(
                    "[worker] company=%s dialer completed | result=%s",
                    target_company_id,
                    metric["dialer_results"],
                )
            except Exception as dialer_err:  # noqa: BLE001
                logger.exception(
                    "[worker] company=%s dialer FAILED – continuing to campaign step",
                    target_company_id,
                )
                metric["dialer_results"] = {"error": str(dialer_err)}

            # Campaign – isolated: a campaign failure must NOT mask dialer result
            try:
                metric["campaign_results"] = run_due_campaign_recipients(
                    session=session,
                    actor_user_id=actor_user_id,
                    company_id=target_company_id,
                )
                logger.info(
                    "[worker] company=%s campaign completed | result=%s",
                    target_company_id,
                    metric["campaign_results"],
                )
            except Exception as campaign_err:  # noqa: BLE001
                logger.exception(
                    "[worker] company=%s campaign FAILED",
                    target_company_id,
                )
                metric["campaign_results"] = {"error": str(campaign_err)}

            # ISM – isolated: ISM failure must NOT mask dialer/campaign results
            try:
                metric["ism_results"] = run_ism_for_company(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                )
                logger.info(
                    "[worker] company=%s ISM completed | leads_processed=%s",
                    target_company_id,
                    len(metric["ism_results"]),
                )
            except Exception as ism_err:  # noqa: BLE001
                logger.exception(
                    "[worker] company=%s ISM FAILED",
                    target_company_id,
                )
                metric["ism_results"] = {"error": str(ism_err)}

            metric["status"] = "completed"

        except Exception as outer_err:  # noqa: BLE001
            # Catch-all: should not normally be reached given inner try/except blocks
            logger.exception(
                "[worker] company=%s UNHANDLED failure",
                target_company_id,
            )
            metric["status"] = "failed"
            metric["error"] = str(outer_err)

        finally:
            # Always release the advisory lock, even if work exploded
            try:
                _release_company_lock(session, target_company_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[worker] company=%s failed to release advisory lock",
                    target_company_id,
                )

            _finalize_metric(metric, company_start)
            results.append(metric)

        logger.info(
            "[worker] company=%s finished | status=%s | duration=%.3fs",
            target_company_id,
            metric["status"],
            metric["duration_seconds"],
        )

    # Cycle-level metrics
    cycle_end = datetime.utcnow()
    cycle_duration = (cycle_end - cycle_start).total_seconds()
    failed_companies = [r for r in results if r["status"] == "failed"]

    _health["last_cycle_at"] = cycle_end.isoformat()
    _health["last_cycle_status"] = "completed" if not failed_companies else "partial_failure"
    _health["last_cycle_duration_seconds"] = cycle_duration
    _health["last_cycle_company_count"] = len(companies)
    _health["last_cycle_results"] = results
    _health["total_cycles"] += 1
    if failed_companies:
        _health["total_failed_cycles"] += 1

    logger.info(
        "[worker] cycle finished | duration=%.2fs | companies=%d | failed=%d",
        cycle_duration,
        len(companies),
        len(failed_companies),
    )

    return results


def run_worker_forever(
    poll_interval_seconds: int = 60,
    company_id: int | None = None,
    dial_limit_per_company: int = 20,
) -> None:
    """Run worker cycles indefinitely, sleeping *poll_interval_seconds* between them.

    This function itself is intentionally simple – crash recovery / exponential
    back-off is handled by the supervisor loop in run_automation_worker.py.
    """
    while True:
        try:
            with Session(engine) as session:
                run_worker_cycle(
                    session=session,
                    company_id=company_id,
                    dial_limit_per_company=dial_limit_per_company,
                )
        except Exception:  # noqa: BLE001
            logger.exception("[worker] run_worker_forever: unexpected error in cycle")

        logger.debug("[worker] sleeping %ds before next cycle", poll_interval_seconds)
        time.sleep(poll_interval_seconds)


# Internal helpers

def _finalize_metric(metric: dict[str, Any], start: datetime) -> None:
    """Stamp end_at and duration_seconds onto *metric* in-place."""
    now = datetime.utcnow()
    metric["end_at"] = now.isoformat()
    metric["duration_seconds"] = (now - start).total_seconds()
