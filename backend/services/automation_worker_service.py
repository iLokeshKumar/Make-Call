from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from agents.ism_orchestrator import run_ism_for_company
from database import engine
from models.models import BackgroundJob, Interaction, User, utc_now
from services.campaign_service import run_due_campaign_recipients
from services.dialer_service import run_batch_dialer
from services.email_outbox_service import process_outbox_batch

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
_last_sentiment_cleanup_at: datetime | None = None


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


# Sentiment event cleanup (runs once per hour across all companies)

def _run_sentiment_cleanup_if_due(session: Session) -> None:
    global _last_sentiment_cleanup_at
    now = datetime.now(timezone.utc)
    if _last_sentiment_cleanup_at and (now - _last_sentiment_cleanup_at).total_seconds() < 3600:
        return
    try:
        cutoff = now - timedelta(minutes=30)
        result = session.execute(
            text("DELETE FROM sentiment_events WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        session.commit()
        logger.info("[worker] sentiment_cleanup deleted %d rows", result.rowcount)
    except Exception:
        logger.exception("[worker] sentiment_cleanup failed")
    finally:
        _last_sentiment_cleanup_at = now


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

    global _last_sentiment_cleanup_at
    _run_sentiment_cleanup_if_due(session)

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
            "email_outbox_results": None,
            "job_results": None,
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

            # Email outbox - isolated and retriable
            try:
                metric["email_outbox_results"] = process_outbox_batch(
                    session=session,
                    company_id=target_company_id,
                    limit=20,
                )
            except Exception as outbox_err:  # noqa: BLE001
                logger.exception(
                    "[worker] company=%s email outbox FAILED",
                    target_company_id,
                )
                metric["email_outbox_results"] = {"error": str(outbox_err)}

            # Background jobs — crash-safe post-call workflows and other deferred work
            try:
                metric["job_results"] = run_pending_jobs(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                )
                logger.info(
                    "[worker] company=%s jobs completed | count=%s",
                    target_company_id,
                    len(metric["job_results"]),
                )
            except Exception as jobs_err:  # noqa: BLE001
                logger.exception("[worker] company=%s background jobs FAILED", target_company_id)
                metric["job_results"] = {"error": str(jobs_err)}

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


# ---------------------------------------------------------------------------
# Background job queue — crash-safe post-call and other deferred work
# ---------------------------------------------------------------------------

_STALE_JOB_MINUTES = 10  # jobs stuck in "running" longer than this are reset
_JOB_RETRY_BACKOFF_MINUTES = 5  # base back-off per attempt on failure


def _reset_stale_running_jobs(session: Session, company_id: int) -> int:
    """
    Find background_jobs stuck in status='running' for more than
    _STALE_JOB_MINUTES (worker crashed mid-execution) and reset them to
    'pending' so they are retried on the next cycle.

    Returns the number of rows reset.
    """
    stale_threshold = utc_now() - timedelta(minutes=_STALE_JOB_MINUTES)
    stale = session.exec(
        select(BackgroundJob).where(
            BackgroundJob.company_id == company_id,
            BackgroundJob.status == "running",
            BackgroundJob.started_at < stale_threshold,
        )
    ).all()
    for job in stale:
        logger.warning(
            "[jobs] Resetting stale job id=%s type=%s (started_at=%s)",
            job.id, job.job_type, job.started_at,
        )
        job.status = "pending"
        job.run_after = utc_now()
        session.add(job)
    if stale:
        session.commit()
    return len(stale)


def _execute_post_call_job(session: Session, job: BackgroundJob) -> dict:
    """
    Execute a post_call_workflow job.

    Reads the interaction transcript from the DB, runs
    extract_and_save_requirements (async, bridged via asyncio.run), then
    dispatch_next_action (sync).  Returns a status dict.
    """
    payload = job.payload or {}
    interaction_id = payload.get("interaction_id")
    lead_id = payload.get("lead_id")
    actor_user_id = payload.get("actor_user_id")

    if not interaction_id or not lead_id or not actor_user_id:
        raise ValueError(f"post_call_workflow job {job.id} has incomplete payload: {payload}")

    interaction = session.get(Interaction, interaction_id)
    if not interaction:
        return {"status": "skipped", "reason": "interaction_not_found", "interaction_id": interaction_id}
    if not interaction.transcript:
        return {"status": "skipped", "reason": "no_transcript", "interaction_id": interaction_id}

    # Local imports keep circular-dependency surface small and avoid loading
    # LLM/ML modules in the worker unless an actual job needs them.
    from credentials_service import get_company_setting_value
    from services.llm import get_llm_service
    from services.post_call_service import extract_and_save_requirements
    from services.next_action_service import dispatch_next_action

    mistral_api_key = get_company_setting_value(session, job.company_id, "MISTRAL_API_KEY")
    llm_service = get_llm_service(
        "mistral",
        "You extract structured B2B sales requirements from transcripts.",
        api_key=mistral_api_key,
    )

    # extract_and_save_requirements is async; worker runs in a plain sync
    # process so we bridge with asyncio.run() (creates a fresh event loop).
    saved = asyncio.run(
        extract_and_save_requirements(
            session=session,
            llm_service=llm_service,
            company_id=job.company_id,
            actor_user_id=actor_user_id,
            interaction_id=interaction_id,
            lead_id=lead_id,
            transcript=interaction.transcript,
        )
    )

    if not saved:
        return {"status": "no_requirements_extracted", "interaction_id": interaction_id}

    dispatch_result = dispatch_next_action(
        session=session,
        company_id=job.company_id,
        actor_user_id=actor_user_id,
        lead_id=lead_id,
        requirement=saved,
    )
    return {
        "status": "processed",
        "interaction_id": interaction_id,
        "requirement_id": saved.id,
        "dispatch_result": dispatch_result,
    }


_JOB_EXECUTORS = {
    "post_call_workflow": _execute_post_call_job,
}


def run_pending_jobs(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 10,
) -> list[dict]:
    """
    Claim up to *limit* pending background jobs for *company_id*, execute
    each one, then mark done or failed.

    The company-level PostgreSQL advisory lock (held by run_worker_cycle)
    prevents two workers from processing the same company concurrently, so we
    don't need SELECT FOR UPDATE here — the lock is cheaper and already held.

    On failure the job is put back to 'pending' with an exponential run_after
    delay and retried up to max_attempts times, then permanently failed.
    """
    _reset_stale_running_jobs(session, company_id)

    now = utc_now()
    jobs = session.exec(
        select(BackgroundJob).where(
            BackgroundJob.company_id == company_id,
            BackgroundJob.status == "pending",
            BackgroundJob.run_after <= now,
            BackgroundJob.attempts < BackgroundJob.max_attempts,
        ).order_by(BackgroundJob.created_at.asc()).limit(limit)
    ).all()

    results: list[dict] = []
    for job in jobs:
        # Claim
        job.status = "running"
        job.started_at = utc_now()
        job.attempts += 1
        session.add(job)
        session.commit()

        executor = _JOB_EXECUTORS.get(job.job_type)
        if executor is None:
            logger.error("[jobs] Unknown job_type=%s id=%s — marking failed", job.job_type, job.id)
            job.status = "failed"
            job.finished_at = utc_now()
            job.error = f"No executor registered for job_type={job.job_type!r}"
            session.add(job)
            session.commit()
            results.append({"job_id": job.id, "status": "failed", "error": job.error})
            continue

        try:
            result = executor(session, job)
            job.status = "done"
            job.finished_at = utc_now()
            job.error = None
            session.add(job)
            session.commit()
            logger.info("[jobs] id=%s type=%s done | result=%s", job.id, job.job_type, result)
            results.append({"job_id": job.id, "status": "done", "result": result})

        except Exception as exc:  # noqa: BLE001
            logger.exception("[jobs] id=%s type=%s attempt=%s FAILED", job.id, job.job_type, job.attempts)
            backoff_minutes = _JOB_RETRY_BACKOFF_MINUTES * job.attempts
            if job.attempts >= job.max_attempts:
                job.status = "failed"
            else:
                job.status = "pending"
                job.run_after = utc_now() + timedelta(minutes=backoff_minutes)
            job.finished_at = utc_now()
            job.error = str(exc)
            session.add(job)
            session.commit()
            results.append({"job_id": job.id, "status": job.status, "error": str(exc)})

    return results
