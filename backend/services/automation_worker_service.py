from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from database import engine
from models.models import User
from services.campaign_service import run_due_campaign_recipients
from services.dialer_service import run_batch_dialer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

worker_health_state: dict[str, Any] = {
    "last_cycle_at": None,
    "last_cycle_status": "never",
    "last_cycle_result": None,
    "total_cycles": 0,
}

def get_worker_health() -> dict[str, Any]:
    return {
        "last_cycle_at": worker_health_state["last_cycle_at"],
        "last_cycle_status": worker_health_state["last_cycle_status"],
        "total_cycles": worker_health_state["total_cycles"],
        "last_cycle_result": worker_health_state["last_cycle_result"],
    }



def get_company_actor_ids(session: Session, company_id: int | None = None) -> dict[int, int]:
    query = select(User).where(User.is_active == True)
    if company_id is not None:
        query = query.where(User.company_id == company_id)

    users = session.exec(query.order_by(User.company_id.asc(), User.id.asc())).all()
    actors: dict[int, int] = {}
    for user in users:
        actors.setdefault(user.company_id, user.id)
    return actors


def _acquire_company_lock(session: Session, company_id: int) -> bool:
    with session.begin():
        result = session.exec(text("SELECT pg_try_advisory_lock(:key)"), {"key": company_id}).one_or_none()
        return bool(result)


def _release_company_lock(session: Session, company_id: int) -> None:
    with session.begin():
        session.exec(text("SELECT pg_advisory_unlock(:key)"), {"key": company_id})


# Health state (module-level) for monitoring endpoints
last_worker_cycle_at: datetime | None = None
last_worker_cycle_duration_seconds: float | None = None
last_worker_cycle_status: str = "never"
last_worker_cycle_results: list[dict[str, Any]] = []


def get_worker_health() -> dict[str, Any]:
    return {
        "last_cycle_at": last_worker_cycle_at.isoformat() if last_worker_cycle_at else None,
        "last_cycle_duration_seconds": last_worker_cycle_duration_seconds,
        "last_cycle_status": last_worker_cycle_status,
        "last_cycle_company_count": len(last_worker_cycle_results) if last_worker_cycle_results is not None else 0,
        "last_cycle_results": last_worker_cycle_results,
    }


def run_worker_cycle(
    session: Session,
    company_id: int | None = None,
    dial_limit_per_company: int = 20,
) -> list[dict[str, Any]]:
    global last_worker_cycle_at, last_worker_cycle_duration_seconds, last_worker_cycle_status, last_worker_cycle_results
    results: list[dict[str, Any]] = []
    cycle_start = datetime.utcnow()
    companies = get_company_actor_ids(session, company_id=company_id)

    logger.info("Worker cycle started: company_id=%s, companies=%s", company_id, list(companies.keys()))

    for target_company_id, actor_user_id in companies.items():
        company_start = datetime.utcnow()
        metric = {
            "company_id": target_company_id,
            "actor_user_id": actor_user_id,
            "status": "skipped",
            "dialer_results": None,
            "campaign_results": None,
            "error": None,
            "start_at": company_start.isoformat(),
            "end_at": None,
            "duration_seconds": None,
        }

        got_lock = _acquire_company_lock(session, target_company_id)
        if not got_lock:
            logger.warning("Skipping company %s: lock held by another worker", target_company_id)
            metric["status"] = "lock_skipped"
            metric["end_at"] = datetime.utcnow().isoformat()
            metric["duration_seconds"] = (datetime.utcnow() - company_start).total_seconds()
            results.append(metric)
            continue

        try:
            try:
                dialer_results = run_batch_dialer(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                    limit=dial_limit_per_company,
                )
            except Exception as e:
                logger.exception("Dialer failure for company %s", target_company_id)
                dialer_results = {"error": str(e)}

            try:
                campaign_results = run_due_campaign_recipients(
                    session=session,
                    actor_user_id=actor_user_id,
                    company_id=target_company_id,
                )
            except Exception as e:
                logger.exception("Campaign processing failure for company %s", target_company_id)
                campaign_results = {"error": str(e)}

            metric["dialer_results"] = dialer_results
            metric["campaign_results"] = campaign_results
            metric["status"] = "completed"

        except Exception as e:
            logger.exception("Unhandled worker failure for company %s", target_company_id)
            metric["status"] = "failed"
            metric["error"] = str(e)

        finally:
            try:
                _release_company_lock(session, target_company_id)
            except Exception as unlock_err:
                logger.exception("Failed to release lock for company %s", target_company_id)

            metric["end_at"] = datetime.utcnow().isoformat()
            metric["duration_seconds"] = (datetime.utcnow() - company_start).total_seconds()
            results.append(metric)

    cycle_end = datetime.utcnow()
    duration = (cycle_end - cycle_start).total_seconds()
    logger.info(
        "Worker cycle completed: duration=%.2fs, companies=%d",
        duration,
        len(companies),
    )

    worker_health_state["last_cycle_at"] = cycle_end.isoformat()
    worker_health_state["last_cycle_status"] = "completed"
    worker_health_state["last_cycle_result"] = {
        "duration_seconds": duration,
        "company_count": len(companies),
        "results": results,
    }
    worker_health_state["total_cycles"] += 1

    return results


def run_worker_forever(
    poll_interval_seconds: int = 60,
    company_id: int | None = None,
    dial_limit_per_company: int = 20,
) -> None:
    while True:
        with Session(engine) as session:
            run_worker_cycle(
                session=session,
                company_id=company_id,
                dial_limit_per_company=dial_limit_per_company,
            )
        time.sleep(poll_interval_seconds)
