from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, text
from sqlmodel import Session, select

from agents.ism_orchestrator import run_ism_for_company
from database import engine, rls_company_id
from models.models import BackgroundJob, CallTask, Company, EmailOutbox, Interaction, User, utc_now
from services.campaign.campaign_service import run_due_campaign_recipients
from services.campaign.dialer_service import run_batch_dialer
from services.communication.email_outbox_service import process_outbox_batch
from services.agent.agent_task_service import run_agent_tasks
from services.agent.agent_approval_service import expire_stale as expire_stale_approvals
from utils.async_bridge import run_async_from_sync

logger = logging.getLogger(__name__)


# Closer silence-scan throttle.  Maps company_id → monotonic timestamp of the
# last scan.  Scanning is cheap (one SELECT) but re-running every worker cycle
# would generate duplicate (idempotent) AgentTasks per-company so we cap at
# 15 minutes.  Module-level so each process retains its own throttle across
# worker cycles.
_CLOSER_SCAN_COOLDOWN_SECONDS = 15 * 60
_closer_scan_last_at: dict[int, float] = {}


def _enqueue_closer_tasks_for_silent_quotes(
    session: Session,
    company_id: int,
    actor_user_id: int,
) -> dict[str, Any]:
    """Scan quotes silent ≥ 3 days + enqueue closer_followup AgentTasks.

    A quote is considered silent if:
      * `sent_at` is set and is at least 3 days old
      * `status` is in {sent, opened, negotiation}
      * there is no inbound Interaction after `sent_at`
      * the Lead is not in a terminal ism_stage (closed_won / closed_lost /
        nurture_pause) and is not soft-deleted

    Idempotency key `closer:{quote_id}:{silence_days}` ensures re-scans on the
    same day dedupe; the next day the silence_days bucket advances and a fresh
    task is allowed.
    """
    from models.models import Lead, Quote, Interaction
    from services.agent.agent_task_service import create_agent_task

    now = utc_now()
    threshold = now - timedelta(days=3)

    active_statuses = ("sent", "opened", "negotiation")
    terminal_stages = ("closed_won", "closed_lost", "nurture_pause")

    quotes = session.exec(
        select(Quote).where(
            Quote.company_id == company_id,
            Quote.deleted_at.is_(None),
            Quote.sent_at.is_not(None),
            Quote.sent_at <= threshold,
            Quote.status.in_(active_statuses),
        ).order_by(Quote.sent_at.asc()).limit(50)
    ).all()

    enqueued = 0
    skipped: list[str] = []

    for quote in quotes:
        lead = session.exec(
            select(Lead).where(
                Lead.id == quote.lead_id,
                Lead.company_id == company_id,
                Lead.deleted_at.is_(None),
            )
        ).first()
        if lead is None:
            skipped.append(f"quote={quote.id}:lead_missing")
            continue
        if (lead.ism_stage or "") in terminal_stages:
            skipped.append(f"quote={quote.id}:lead_stage_{lead.ism_stage}")
            continue

        last_inbound = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead.id,
                Interaction.direction == "inbound",
                Interaction.started_at > quote.sent_at,
            ).order_by(Interaction.started_at.desc()).limit(1)
        ).first()
        if last_inbound is not None:
            skipped.append(f"quote={quote.id}:has_inbound")
            continue

        sent_at_utc = quote.sent_at
        if sent_at_utc.tzinfo is None:
            sent_at_utc = sent_at_utc.replace(tzinfo=timezone.utc)
        silence_days = max((now - sent_at_utc).days, 3)

        try:
            create_agent_task(
                session=session,
                company_id=company_id,
                task_type="closer_followup",
                assigned_agent="closer",
                input_json={
                    "lead_id": lead.id,
                    "quote_id": quote.id,
                    "silence_days": silence_days,
                },
                lead_id=lead.id,
                idempotency_key=f"closer:{quote.id}:{silence_days}",
                actor_user_id=actor_user_id,
            )
            enqueued += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[closer_scan] enqueue failed for quote=%s: %s", quote.id, exc)
            skipped.append(f"quote={quote.id}:enqueue_error")

    return {"enqueued": enqueued, "scanned": len(quotes), "skipped": skipped}


def _maybe_enqueue_closer_tasks_for_company(
    session: Session,
    company_id: int,
    actor_user_id: int,
) -> dict[str, Any]:
    """Throttled wrapper — skip if we scanned this company < 15 min ago."""
    last = _closer_scan_last_at.get(company_id)
    mono = time.monotonic()
    if last is not None and (mono - last) < _CLOSER_SCAN_COOLDOWN_SECONDS:
        return {"skipped": "throttled_15min"}

    result = _enqueue_closer_tasks_for_silent_quotes(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
    )
    _closer_scan_last_at[company_id] = mono
    return result


def _reset_closer_scan_throttle_for_tests() -> None:
    """Test hook — clear the per-company throttle state."""
    _closer_scan_last_at.clear()


# SLO evaluation cadence + per-SLO dedupe.
# Outer dict: company_id → last evaluation monotonic time (15-min cap).
# Inner dict: (company_id, slo_id) → last alert monotonic time (60-min dedupe).
_SLO_EVAL_COOLDOWN_SECONDS = 15 * 60
_SLO_ALERT_DEDUPE_SECONDS = 60 * 60
_slo_eval_last_at: dict[int, float] = {}
_slo_alert_last_at: dict[tuple[int, str], float] = {}


def _slo_alerts_enabled() -> bool:
    """Soft-launch gate.  Returns False until SLO_ALERTS_ENABLED_AT passes.

    Day-one rollout will breach voice p95 immediately (current state >800ms).
    Set SLO_ALERTS_ENABLED_AT to an ISO timestamp 24h in the future so the
    user can tune SLOs against real data without alert noise.
    """
    raw = os.getenv("SLO_ALERTS_ENABLED_AT", "").strip()
    if not raw:
        return True  # default: alerts on
    try:
        threshold = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if threshold.tzinfo is None:
            threshold = threshold.replace(tzinfo=timezone.utc)
        return utc_now() >= threshold
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to parse SLO alert enabled_at timestamp: %s",
            str(e),
            extra={"raw_value": raw}
        )
        # Bad ISO → fail-safe enable so a typo doesn't permanently silence alerts.
        return True


def _maybe_evaluate_slos_and_alert(
    session: Session,
    company_id: int,
) -> dict[str, Any]:
    """Throttled wrapper — skip if last eval < 15 min ago for this company."""
    now_mono = time.monotonic()
    last = _slo_eval_last_at.get(company_id)
    if last is not None and (now_mono - last) < _SLO_EVAL_COOLDOWN_SECONDS:
        return {"skipped": "throttled_15min"}

    if not _slo_alerts_enabled():
        _slo_eval_last_at[company_id] = now_mono
        return {"skipped": "soft_launch_window", "alerts_enabled_at": os.getenv("SLO_ALERTS_ENABLED_AT")}

    try:
        from services.observability.slo import evaluate_all
        from services.alerts import notify_breach_sync
    except Exception as exc:  # noqa: BLE001
        logger.warning("[slo] eval import failed: %s", exc)
        return {"error": str(exc)}

    breaches: list[str] = []
    for slo in evaluate_all(session, company_id):
        if slo["status"] != "breach":
            continue
        key = (company_id, slo["id"])
        last_alert = _slo_alert_last_at.get(key)
        if last_alert is not None and (now_mono - last_alert) < _SLO_ALERT_DEDUPE_SECONDS:
            continue
        try:
            notify_breach_sync(
                slo_id=slo["id"],
                actual=slo.get("actual"),
                target=slo.get("target"),
                severity="high",
            )
            _slo_alert_last_at[key] = now_mono
            breaches.append(slo["id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[slo] alert dispatch failed for %s: %s", slo["id"], exc)

    _slo_eval_last_at[company_id] = now_mono
    return {"breaches_alerted": breaches}


def _reset_slo_throttles_for_tests() -> None:
    _slo_eval_last_at.clear()
    _slo_alert_last_at.clear()


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

# Dead-letter / failed-job alerting
_DEAD_LETTER_THRESHOLD: int = int(os.getenv("DEAD_LETTER_THRESHOLD", "3"))
_DEAD_LETTER_WINDOW_MINUTES: int = 60       # look-back window for failed row counts
_DEAD_LETTER_COOLDOWN_MINUTES: int = 60     # max one alert email per company per hour
_dead_letter_last_alerted: dict[int, datetime] = {}  # company_id → last alert time


def get_worker_health() -> dict[str, Any]:
    """Return a snapshot of the latest worker-cycle health metrics."""
    return {**_health, "paused": _paused}


def pause_worker() -> dict[str, Any]:
    """Pause the automation worker so future cycle invocations are no-ops."""
    global _paused
    _paused = True
    logger.info("worker paused", extra={"event": "worker_paused", "worker_name": "automation_worker"})
    return get_worker_health()


def resume_worker() -> dict[str, Any]:
    """Resume the automation worker after a pause."""
    global _paused
    _paused = False
    logger.info("worker resumed", extra={"event": "worker_resumed", "worker_name": "automation_worker"})
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
        cse_cutoff = now - timedelta(hours=4)
        result2 = session.execute(
            text("DELETE FROM call_status_events WHERE created_at < :cutoff"),
            {"cutoff": cse_cutoff},
        )
        session.commit()
        logger.info("sentiment cleanup complete", extra={
            "event": "sentiment_cleanup",
            "sentiment_rows_deleted": result.rowcount,
            "call_status_rows_deleted": result2.rowcount,
            "worker_name": "automation_worker",
        })
    except Exception:
        logger.exception("sentiment cleanup failed", extra={
            "event": "sentiment_cleanup_error",
            "worker_name": "automation_worker",
        })
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

    logger.info("worker cycle started", extra={
        "event": "worker_cycle_start",
        "company_filter": company_id,
        "company_count": len(companies),
        "company_ids": list(companies.keys()),
        "worker_name": "automation_worker",
    })

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
            logger.warning("company skipped — lock held by another instance", extra={
                "event": "worker_lock_skip",
                "company_id": target_company_id,
                "worker_name": "automation_worker",
            })
            metric["status"] = "lock_skipped"
            _finalize_metric(metric, company_start)
            results.append(metric)
            continue

        # Pin RLS context so every DB query in this iteration is scoped to
        # the correct tenant — same mechanism the HTTP middleware uses.
        _rls_token = rls_company_id.set(target_company_id)

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
                logger.info("dialer completed", extra={
                    "event": "dialer_complete",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
            except Exception as dialer_err:  # noqa: BLE001
                logger.exception("dialer failed", extra={
                    "event": "dialer_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["dialer_results"] = {"error": str(dialer_err)}

            # Campaign – isolated: a campaign failure must NOT mask dialer result
            try:
                metric["campaign_results"] = run_due_campaign_recipients(
                    session=session,
                    actor_user_id=actor_user_id,
                    company_id=target_company_id,
                )
                logger.info("campaign completed", extra={
                    "event": "campaign_complete",
                    "company_id": target_company_id,
                    "result_count": len(metric["campaign_results"]) if isinstance(metric["campaign_results"], list) else None,
                    "worker_name": "automation_worker",
                })
            except Exception as campaign_err:  # noqa: BLE001
                logger.exception("campaign failed", extra={
                    "event": "campaign_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["campaign_results"] = {"error": str(campaign_err)}

            # ISM – isolated: ISM failure must NOT mask dialer/campaign results
            try:
                metric["ism_results"] = run_ism_for_company(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                )
                logger.info("ISM completed", extra={
                    "event": "ism_complete",
                    "company_id": target_company_id,
                    "leads_processed": len(metric["ism_results"]) if isinstance(metric["ism_results"], list) else 0,
                    "worker_name": "automation_worker",
                })
            except Exception as ism_err:  # noqa: BLE001
                logger.exception("ISM failed", extra={
                    "event": "ism_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["ism_results"] = {"error": str(ism_err)}

            # Closer — enqueue follow-up tasks for silent quotes.  Throttled
            # per-company so we only scan every 15 minutes even if the worker
            # cycle fires more often.
            try:
                metric["closer_enqueued"] = _maybe_enqueue_closer_tasks_for_company(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                )
            except Exception as closer_err:  # noqa: BLE001
                logger.exception("closer scan failed", extra={
                    "event": "closer_scan_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["closer_enqueued"] = {"error": str(closer_err)}

            # SLO evaluation + breach alerting — throttled to 15min per company.
            try:
                metric["slo_eval"] = _maybe_evaluate_slos_and_alert(
                    session=session,
                    company_id=target_company_id,
                )
            except Exception as slo_err:  # noqa: BLE001
                logger.exception("slo eval failed", extra={
                    "event": "slo_eval_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["slo_eval"] = {"error": str(slo_err)}

            # Email outbox - isolated and retriable
            try:
                metric["email_outbox_results"] = process_outbox_batch(
                    session=session,
                    company_id=target_company_id,
                    limit=20,
                )
            except Exception as outbox_err:  # noqa: BLE001
                logger.exception("email outbox failed", extra={
                    "event": "outbox_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["email_outbox_results"] = {"error": str(outbox_err)}

            # Background jobs — crash-safe post-call workflows and other deferred work
            try:
                metric["job_results"] = run_pending_jobs(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                )
                logger.info("background jobs completed", extra={
                    "event": "jobs_complete",
                    "company_id": target_company_id,
                    "job_count": len(metric["job_results"]),
                    "worker_name": "automation_worker",
                })
            except Exception as jobs_err:  # noqa: BLE001
                logger.exception("background jobs failed", extra={
                    "event": "jobs_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["job_results"] = {"error": str(jobs_err)}

            # Agent tasks — execute pending orchestrator-created tasks
            try:
                metric["agent_task_results"] = run_agent_tasks(
                    session=session,
                    company_id=target_company_id,
                    actor_user_id=actor_user_id,
                )
                logger.info("agent tasks completed", extra={
                    "event": "agent_tasks_complete",
                    "company_id": target_company_id,
                    "results": metric["agent_task_results"],
                    "worker_name": "automation_worker",
                })
            except Exception as agent_task_err:  # noqa: BLE001
                logger.exception("agent tasks failed", extra={
                    "event": "agent_tasks_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })
                metric["agent_task_results"] = {"error": str(agent_task_err)}

            # Expire stale approval requests past their deadline
            try:
                expired = expire_stale_approvals(session=session, company_id=target_company_id)
                if expired:
                    metric["expired_approvals"] = expired
            except Exception as expire_err:  # noqa: BLE001
                logger.warning("approval expiry failed for company %s: %s", target_company_id, expire_err)

            # Dead-letter check — runs last so it counts failures from this cycle too
            try:
                _check_dead_letter_threshold(session, target_company_id, actor_user_id)
            except Exception:  # noqa: BLE001
                logger.exception("dead-letter check error", extra={
                    "event": "dead_letter_check_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })

            metric["status"] = "completed"

        except Exception as outer_err:  # noqa: BLE001
            # Catch-all: should not normally be reached given inner try/except blocks
            logger.exception("company cycle unhandled failure", extra={
                "event": "worker_company_error",
                "company_id": target_company_id,
                "worker_name": "automation_worker",
            })
            metric["status"] = "failed"
            metric["error"] = str(outer_err)

        finally:
            # Always release the advisory lock, even if work exploded
            try:
                _release_company_lock(session, target_company_id)
            except Exception:  # noqa: BLE001
                logger.exception("failed to release advisory lock", extra={
                    "event": "worker_lock_release_error",
                    "company_id": target_company_id,
                    "worker_name": "automation_worker",
                })

            rls_company_id.reset(_rls_token)
            _finalize_metric(metric, company_start)
            results.append(metric)

        logger.info("company cycle finished", extra={
            "event": "worker_company_done",
            "company_id": target_company_id,
            "status": metric["status"],
            "duration_seconds": metric["duration_seconds"],
            "worker_name": "automation_worker",
        })

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

    logger.info("worker cycle finished", extra={
        "event": "worker_cycle_done",
        "duration_seconds": round(cycle_duration, 2),
        "company_count": len(companies),
        "failed_count": len(failed_companies),
        "cycle_status": _health["last_cycle_status"],
        "total_cycles": _health["total_cycles"],
        "worker_name": "automation_worker",
    })

    return results


def _safe_run_cycle(
    trigger: str,
    company_id: int | None,
    dial_limit_per_company: int,
) -> None:
    """Run one cycle in a fresh session. Exceptions are logged, never raised
    (the supervisor's outer try/except would restart the whole worker, which
    is overkill for a transient per-cycle failure).
    """
    try:
        with Session(engine) as session:
            run_worker_cycle(
                session=session,
                company_id=company_id,
                dial_limit_per_company=dial_limit_per_company,
            )
    except Exception:  # noqa: BLE001
        logger.exception(
            "[worker] cycle failed",
            extra={"trigger": trigger, "company_id": company_id},
        )


def run_worker_forever(
    poll_interval_seconds: int = 60,
    company_id: int | None = None,
    dial_limit_per_company: int = 20,
) -> None:
    """Run worker cycles indefinitely.

    Event-driven mode (Postgres, default): the worker LISTENs on
    `agent_task_ready`. On wake with payloads, runs a TARGETED cycle for
    each notified company. On tick (timeout), runs a full multi-company
    cycle as safety net. First pass after startup runs a full cycle so
    any work queued before the worker booted is picked up immediately.

    Polling mode (sqlite / `WORKER_LISTEN_NOTIFY=0`): wake is just a timer;
    every wake runs a full cycle.

    --company-id restricts the worker to one tenant. In that mode, NOTIFYs
    for other companies are ignored (the advisory lock would skip them
    anyway, but we filter early to avoid the wasted session + log noise).
    """
    from services.notify_listener import is_postgres, listen_connection, wait_for_notify

    use_listen = is_postgres(engine) and os.getenv("WORKER_LISTEN_NOTIFY", "1") == "1"

    with listen_connection(engine) as listen_conn:
        if use_listen and listen_conn is not None:
            logger.info(
                "[worker] event-driven mode: per-company NOTIFY + %ds full-cycle fallback",
                poll_interval_seconds,
            )
        else:
            logger.info("[worker] polling mode: %ds tick → full cycle", poll_interval_seconds)

        # Initial full cycle so startup picks up pre-existing queued work
        # without waiting for the first tick.
        _safe_run_cycle("startup", company_id, dial_limit_per_company)

        while True:
            payloads = wait_for_notify(listen_conn, poll_interval_seconds)

            if not payloads:
                # Timeout — run the full multi-company cycle as safety net.
                _safe_run_cycle("tick", company_id, dial_limit_per_company)
                continue

            # Targeted cycles for each notified company. Set semantics: if the
            # same company NOTIFYs 50 times between wakes, we run one cycle.
            for raw in sorted(payloads):
                try:
                    notified_cid = int(raw)
                except (TypeError, ValueError):
                    logger.warning("[worker] invalid NOTIFY payload: %r", raw)
                    continue

                # Respect --company-id single-tenant filter
                if company_id is not None and notified_cid != company_id:
                    continue

                logger.debug("[worker] targeted cycle for company=%s (NOTIFY)", notified_cid)
                _safe_run_cycle("notify", notified_cid, dial_limit_per_company)


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
        logger.warning("stale job reset to pending", extra={
            "event": "job_stale_reset",
            "job_id": job.id,
            "job_type": job.job_type,
            "company_id": company_id,
            "started_at": str(job.started_at),
            "worker_name": "automation_worker",
        })
        job.status = "pending"
        job.run_after = utc_now()
        session.add(job)
    if stale:
        session.commit()
    return len(stale)


def _check_dead_letter_threshold(
    session: Session, company_id: int, actor_user_id: int
) -> None:
    """Count permanently-failed rows from the last hour across BackgroundJob,
    EmailOutbox, and CallTask.  If the total exceeds _DEAD_LETTER_THRESHOLD,
    emit a CRITICAL log and fire a self-alert email via the company's own SMTP
    credentials.  A per-company in-memory cooldown prevents re-alerting within
    the same hour.
    """
    window_start = utc_now() - timedelta(minutes=_DEAD_LETTER_WINDOW_MINUTES)

    bg_failed: int = session.exec(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.company_id == company_id,
            BackgroundJob.status.in_(["failed", "dead_letter"]),
            BackgroundJob.finished_at >= window_start,
        )
    ).one() or 0

    eo_failed: int = session.exec(
        select(func.count(EmailOutbox.id)).where(
            EmailOutbox.company_id == company_id,
            EmailOutbox.status == "failed",
            EmailOutbox.updated_at >= window_start,
        )
    ).one() or 0

    ct_failed: int = session.exec(
        select(func.count(CallTask.id)).where(
            CallTask.company_id == company_id,
            CallTask.status == "failed",
            CallTask.completed_at >= window_start,
        )
    ).one() or 0

    total = bg_failed + eo_failed + ct_failed

    if total <= _DEAD_LETTER_THRESHOLD:
        return

    # Cooldown: at most one alert per company per hour (in-memory, resets on restart)
    last_alerted = _dead_letter_last_alerted.get(company_id)
    cooldown_boundary = utc_now() - timedelta(minutes=_DEAD_LETTER_COOLDOWN_MINUTES)
    if last_alerted and last_alerted >= cooldown_boundary:
        return

    logger.critical("dead-letter threshold exceeded", extra={
        "event": "dead_letter_alert",
        "company_id": company_id,
        "bg_failed": bg_failed,
        "eo_failed": eo_failed,
        "ct_failed": ct_failed,
        "total_failed": total,
        "threshold": _DEAD_LETTER_THRESHOLD,
        "window_minutes": _DEAD_LETTER_WINDOW_MINUTES,
        "worker_name": "automation_worker",
    })

    _dead_letter_last_alerted[company_id] = utc_now()
    _send_dead_letter_alert(
        session, company_id, actor_user_id, bg_failed, eo_failed, ct_failed, total
    )


def _send_dead_letter_alert(
    session: Session,
    company_id: int,
    actor_user_id: int,
    bg_failed: int,
    eo_failed: int,
    ct_failed: int,
    total: int,
) -> None:
    """Send an alert email to the company admin using their own SMTP credentials.
    Any exception here is caught and logged so it never crashes the worker cycle.
    """
    try:
        from credentials_service import get_email_credential
        from email_service import send_smtp_email

        company = session.get(Company, company_id)
        if not company:
            return

        admin_email = company.contact_email
        if not admin_email:
            logger.warning("dead-letter alert skipped — no contact email", extra={
                "event": "dead_letter_email_skipped",
                "reason": "no_contact_email",
                "company_id": company_id,
                "worker_name": "automation_worker",
            })
            return

        smtp_kwargs = dict(
            smtp_host=get_email_credential(session, company_id, actor_user_id, "SMTP_HOST"),
            smtp_port=get_email_credential(session, company_id, actor_user_id, "SMTP_PORT"),
            smtp_security=get_email_credential(session, company_id, actor_user_id, "SMTP_SECURITY"),
            smtp_username=get_email_credential(session, company_id, actor_user_id, "SMTP_USERNAME"),
            smtp_password=get_email_credential(session, company_id, actor_user_id, "SMTP_PASSWORD"),
            smtp_from_email=get_email_credential(session, company_id, actor_user_id, "SMTP_FROM_EMAIL"),
        )

        if not smtp_kwargs.get("smtp_host"):
            logger.warning("dead-letter alert skipped — no SMTP config", extra={
                "event": "dead_letter_email_skipped",
                "reason": "no_smtp_config",
                "company_id": company_id,
                "worker_name": "automation_worker",
            })
            return

        subject = f"[Rio CRM] Dead-letter alert — {total} jobs failed in the last hour"
        body = (
            f"Dead-letter threshold exceeded for company ID {company_id} ({company.name}).\n\n"
            f"  BackgroundJob failed : {bg_failed}\n"
            f"  EmailOutbox failed   : {eo_failed}\n"
            f"  CallTask failed      : {ct_failed}\n"
            f"  Total                : {total}  (threshold: {_DEAD_LETTER_THRESHOLD})\n\n"
            f"All counts are from the last {_DEAD_LETTER_WINDOW_MINUTES} minutes.\n"
            f"Check failed rows and review service logs for root cause.\n"
        )

        sent = send_smtp_email(
            to_email=admin_email,
            subject=subject,
            body=body,
            company_name=company.name or "Rio CRM",
            **smtp_kwargs,
        )
        if sent:
            logger.info("dead-letter alert email sent", extra={
                "event": "dead_letter_email_sent",
                "company_id": company_id,
                "to": admin_email,
                "worker_name": "automation_worker",
            })
        else:
            logger.warning("dead-letter alert email delivery failed", extra={
                "event": "dead_letter_email_failed",
                "company_id": company_id,
                "worker_name": "automation_worker",
            })

    except Exception:
        logger.exception("dead-letter alert email error", extra={
            "event": "dead_letter_email_error",
            "company_id": company_id,
            "worker_name": "automation_worker",
        })


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

    # Skip LLM pipeline for dead leads. No point burning tokens on soft-deleted
    # leads or ones already in a terminal ISM stage (closed_won/closed_lost).
    from models.models import Lead
    _SKIP_ISM_STAGES = {"closed_won", "closed_lost"}
    lead = session.get(Lead, lead_id)
    if lead is None:
        return {"status": "skipped", "reason": "lead_not_found", "lead_id": lead_id}
    if lead.deleted_at is not None:
        return {"status": "skipped", "reason": "lead_deleted", "lead_id": lead_id}
    if (lead.ism_stage or "") in _SKIP_ISM_STAGES:
        return {"status": "skipped", "reason": f"ism_stage_{lead.ism_stage}", "lead_id": lead_id}

    # Local imports keep circular-dependency surface small and avoid loading
    # LLM/ML modules in the worker unless an actual job needs them.
    from credentials_service import get_company_setting_value
    from services.ai.llm import get_llm_service
    from services.call.post_call_service import extract_and_save_requirements
    from services.next_action_service import dispatch_next_action

    mistral_api_key = get_company_setting_value(session, job.company_id, "MISTRAL_API_KEY")
    llm_service = get_llm_service(
        "mistral",
        "You extract structured B2B sales requirements from transcripts.",
        api_key=mistral_api_key,
    )

    # extract_and_save_requirements is async. The worker may be invoked from a
    # sync entry point (standalone worker process) or from within a running
    # FastAPI event loop (e.g. POST /automation/run-cycle). run_async_from_sync
    # picks the right execution strategy for both using a shared thread pool.
    # It always returns the LeadRequirement if one was created/updated, but
    # it ALSO saves Feedback (verbal rating/comment) to the database independently.
    saved = run_async_from_sync(
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

    # Check if feedback was saved (even if requirements extraction failed)
    from models.models import Feedback
    feedback = session.exec(
        select(Feedback).where(
            Feedback.company_id == job.company_id,
            Feedback.interaction_id == interaction_id,
        ).limit(1)
    ).first()

    if not saved and not feedback:
        return {"status": "no_data_extracted", "interaction_id": interaction_id}

    dispatch_result = None
    if saved:
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
        "requirement_id": saved.id if saved else None,
        "feedback_id": feedback.id if feedback else None,
        "dispatch_result": dispatch_result,
    }


def _execute_noop_smoke_job(session: Session, job: BackgroundJob) -> dict:
    """Trivial executor for the horizontal-scale smoke test.

    Sleeps briefly so wall-clock contention between workers is measurable,
    then returns. Registered only when ALLOW_NOOP_SMOKE_JOBS=1 to keep
    production from accidentally enqueuing it.
    """
    delay_ms = int((job.payload or {}).get("delay_ms", 50))
    time.sleep(max(0, min(delay_ms, 1000)) / 1000.0)
    return {"status": "noop", "worker_pid": os.getpid()}


_JOB_EXECUTORS = {
    "post_call_workflow": _execute_post_call_job,
}

if os.getenv("ALLOW_NOOP_SMOKE_JOBS") == "1":
    _JOB_EXECUTORS["noop_smoke"] = _execute_noop_smoke_job


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

    # Cap LLM-heavy job types per cycle. Each post_call_workflow fires 5
    # sequential Mistral calls at ~1.2s each. Running more than 3 of those
    # back-to-back hammers the free-tier rate limit. Remaining jobs stay
    # pending and are picked up by the next worker cycle.
    _PER_CYCLE_CAPS = {"post_call_workflow": 3}
    if jobs:
        kept: list[BackgroundJob] = []
        counts: dict[str, int] = {}
        for j in jobs:
            cap = _PER_CYCLE_CAPS.get(j.job_type)
            if cap is not None:
                if counts.get(j.job_type, 0) >= cap:
                    continue
                counts[j.job_type] = counts.get(j.job_type, 0) + 1
            kept.append(j)
        jobs = kept

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
            logger.error("unknown job type — marking dead_letter", extra={
                "event": "job_unknown_type",
                "job_id": job.id,
                "job_type": job.job_type,
                "company_id": company_id,
                "worker_name": "automation_worker",
            })
            job.status = "dead_letter"
            job.finished_at = utc_now()
            job.error = f"No executor registered for job_type={job.job_type!r}"
            session.add(job)
            session.commit()
            results.append({"job_id": job.id, "status": "dead_letter", "error": job.error})
            continue

        try:
            result = executor(session, job)
            job.status = "done"
            job.finished_at = utc_now()
            job.error = None
            session.add(job)
            session.commit()
            logger.info("job completed", extra={
                "event": "job_done",
                "job_id": job.id,
                "job_type": job.job_type,
                "company_id": company_id,
                "worker_name": "automation_worker",
            })
            results.append({"job_id": job.id, "status": "done", "result": result})

        except Exception as exc:  # noqa: BLE001
            exhausted = job.attempts >= job.max_attempts
            logger.exception("job failed", extra={
                "event": "job_failed",
                "job_id": job.id,
                "job_type": job.job_type,
                "company_id": company_id,
                "attempt": job.attempts,
                "max_attempts": job.max_attempts,
                "final": exhausted,
                "worker_name": "automation_worker",
            })
            if exhausted:
                job.status = "dead_letter"
                logger.critical("job moved to dead letter", extra={
                    "event": "job_dead_letter",
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "company_id": company_id,
                    "attempts": job.attempts,
                    "worker_name": "automation_worker",
                })
            else:
                # Exponential backoff: 1min, 2min, 4min, 8min, …
                backoff_seconds = 60 * (2 ** job.attempts)
                job.status = "pending"
                job.run_after = utc_now() + timedelta(seconds=backoff_seconds)
            job.finished_at = utc_now()
            job.error = str(exc)
            session.add(job)
            session.commit()
            results.append({"job_id": job.id, "status": job.status, "error": str(exc)})

    return results
