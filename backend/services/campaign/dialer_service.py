from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from sqlmodel import Session, select
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from credentials_service import get_company_credential, get_company_setting_value
from models.models import CallTask, Company, Interaction, Lead, OptOut, User, utc_now
from services.call.outbound_call_service import create_call_task, get_call_task_or_404, start_call_task
from utils.phone import normalize_phone
from utils.url_utils import normalize_base_url
from utils.timezone_utils import (
    business_hours_config_for_company,
    detect_timezone,
    get_company_timezone_from_login_history,
    is_within_business_hours,
)
from services.leads.opt_out_service import is_lead_opted_out
from services.core.usage_service import check_and_increment
from services.core.feature_flag_service import require_feature

def is_lead_callable(session: Session, company_id: int, lead_id: int) -> tuple[bool, str | None]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return False, "lead_not_found"
    if not lead.normalized_phone:
        return False, "missing_phone"

    if is_lead_opted_out(session, company_id, lead_id, "call"):
        return False, "opted_out"

    if (lead.status or "").lower() in {"closed_won", "closed_lost", "do_not_call"}:
        return False, "lead_closed"

    tz_str = lead.timezone
    if not tz_str:
        tz_str = detect_timezone(lead.city, lead.state, lead.country)
        if tz_str == os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata"):

            tz_str = get_company_timezone_from_login_history(session, company_id) or tz_str
    bh = business_hours_config_for_company(session, company_id)
    if not is_within_business_hours(
        tz_str,
        start_hour=bh["start"],
        end_hour=bh["end"],
        sunday_blocked=bh["sunday_blocked"],
        disabled=bh["disabled"],
    ):
        return False, f"outside_business_hours:{tz_str}"

    return True, None


def opt_out_lead_from_calls(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    reason: str | None = None,
) -> OptOut:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    existing = session.exec(
        select(OptOut).where(
            OptOut.company_id == company_id,
            OptOut.lead_id == lead_id,
            OptOut.channel == "call",
        )
    ).first()
    if existing:
        return existing

    opt_out = OptOut(
        company_id=company_id,
        lead_id=lead_id,
        channel="call",
        reason=reason,
    )
    session.add(opt_out)
    lead.status = "do_not_call"
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()
    session.refresh(opt_out)
    return opt_out


def create_batch_call_tasks(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_ids: list[int],
    assigned_user_id: int | None = None,
    batch_id: str | None = None,
    scheduled_at=None,
    notes: str | None = None,
    dialer_source: str = "batch_dialer",
) -> dict:
    created: list[int] = []
    skipped: list[dict[str, str | int]] = []
    normalized_batch_id = batch_id or f"batch-{utc_now().strftime('%Y%m%d%H%M%S')}"

    for lead_id in lead_ids:
        callable_lead, reason = is_lead_callable(session, company_id, lead_id)
        if not callable_lead:
            skipped.append({"lead_id": lead_id, "reason": reason or "not_callable"})
            continue

        task = create_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            assigned_user_id=assigned_user_id,
            scheduled_at=scheduled_at,
            notes=notes,
            batch_id=normalized_batch_id,
            dialer_source=dialer_source,
            initial_status="queued",
        )
        created.append(task.id)

    return {
        "batch_id": normalized_batch_id,
        "created_task_ids": created,
        "created_count": len(created),
        "skipped": skipped,
    }


def get_next_queued_task(session: Session, company_id: int) -> CallTask | None:
    now = utc_now()
    return session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.status.in_(["queued", "retry_scheduled"]),
            (CallTask.scheduled_at.is_(None)) | (CallTask.scheduled_at <= now),
            (CallTask.retry_after.is_(None)) | (CallTask.retry_after <= now),
        ).order_by(CallTask.created_at.asc())
    ).first()


def _resolve_callback_base(session: Session, company_id: int) -> str:
    if env_domain := os.getenv("DOMAIN"):
        return normalize_base_url(env_domain, "https://localhost:8000")
    company = session.get(Company, company_id)
    domain_source = (company.domain if company and company.domain else None) or "localhost:8000"
    return normalize_base_url(domain_source, "https://localhost:8000")


def initiate_outbound_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    to: str,
    lead_id: Optional[int] = None,
    call_task_id: Optional[int] = None,
) -> dict:
    account_sid = get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID")
    auth_token = get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN")
    from_number = (
        get_company_credential(session, company_id, "TWILIO_PHONE_NUMBER")
        or os.getenv("PHONE_NUMBER_FROM")
    )
    if not all([account_sid, auth_token, from_number]):
        raise HTTPException(status_code=400, detail="Twilio credentials are not configured")

    normalized_to = normalize_phone(to)

    # Pre-call workflow via orchestrator (knowledge search + enrichment + ICP score).  Result is stored in precall_cache so voice_pipeline can inject KB context at call start.  Can be disabled for low-latency call paths via ENABLE_PRECALL_RESEARCHER=0.

    # Run synchronously with a budget — `asyncio.create_task` was both racy (Twilio dial fired before precall finished, voice pipeline read empty cache) AND silently no-op'd in worker contexts that have no running event loop.  Sync-wait with a hard timeout guarantees the cache is populated when present, and bounds the dial-start delay if precall is slow / the LLM rate-limits.
    enable_precall_researcher = os.getenv("ENABLE_PRECALL_RESEARCHER", "1").lower() in {"1", "true", "yes", "on"}
    if lead_id and enable_precall_researcher:
        precall_timeout_s = float(os.getenv("PRECALL_TIMEOUT_S", "4.0"))

        async def _run_precall():
            from agents.orchestrator import run_pre_call
            from utils.precall_cache import put as cache_put
            result = await asyncio.wait_for(
                run_pre_call(
                    lead_id=lead_id,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                ),
                timeout=precall_timeout_s,
            )
            cache_put(company_id, lead_id, result)
            logger.info(
                "[Dialer] Pre-call complete for lead %s: icp=%.2f, kb_chunks=%d",
                lead_id,
                result.get("icp_score", 0.0),
                len(result.get("kb_context", [])),
            )

        try:
            import asyncio
            import concurrent.futures
            import contextvars
            try:
                asyncio.get_running_loop()
                # Worker invoked from FastAPI loop — offload to a thread with its own loop.  ContextVars (request_id, trace_id) cross via copy_context so logging stays coherent.
                ctx = contextvars.copy_context()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(ctx.run, asyncio.run, _run_precall()).result()
            except RuntimeError:
                # Sync worker context — no running loop.  Run directly.
                asyncio.run(_run_precall())
        except asyncio.TimeoutError:
            logger.warning(
                "[Dialer] Pre-call exceeded %.1fs budget for lead %s — dialing without KB context",
                precall_timeout_s, lead_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Dialer] Pre-call workflow failed (non-blocking): %s", exc)

    lead = None
    if lead_id:
        allowed, reason = is_lead_callable(session, company_id, lead_id)
        if not allowed:
            raise HTTPException(status_code=400, detail=f"Lead is not callable: {reason}")
        lead = session.exec(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.company_id == company_id,
            )
        ).first()
    else:
        lead = session.exec(
            select(Lead).where(
                Lead.company_id == company_id,
                Lead.normalized_phone == normalized_to,
            )
        ).first()
        if lead:
            allowed, reason = is_lead_callable(session, company_id, lead.id)
            if not allowed:
                raise HTTPException(status_code=400, detail=f"Lead is not callable: {reason}")
            lead_id = lead.id

    actor_user = session.get(User, actor_user_id)
    interaction = Interaction(
        company_id=company_id,
        lead_id=lead_id,
        user_id=actor_user_id,
        type="call",
        channel="call",
        direction="outbound",
        source="twilio",
        content="Outbound Call",
        status="active",
        started_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    if call_task_id:
        start_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            task_id=call_task_id,
            interaction_id=interaction.id,
        )

    callback_base = _resolve_callback_base(session, company_id)
    call_url = (
        f"{callback_base}/outgoing-call"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}"
    )
    status_callback = (
        f"{callback_base}/twilio/status-callback"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}"
    )

    recording_callback = (
        f"{callback_base}/twilio/recording-callback"
        f"?interaction_id={interaction.id}"
    )

    require_feature(session, company_id, "outbound_calls")
    check_and_increment(session, company_id, "calls_made")

    client = TwilioClient(account_sid, auth_token)
    try:
        call = client.calls.create(
            to=normalized_to,
            from_=from_number,
            url=call_url,
            status_callback=status_callback,
            status_callback_event=["initiated", "ringing", "in-progress", "completed", "busy", "no-answer", "failed", "canceled"],
            status_callback_method="POST",
            record=True,
            recording_status_callback=recording_callback,
            recording_status_callback_method="POST",
        )
    except TwilioRestException as exc:
        if exc.code in (20003, 20005):
            raise HTTPException(
                status_code=402,
                detail=f"Twilio account error ({exc.code}): {exc.msg}. Check credentials or account balance.",
            )
        if exc.code in (21210, 21211, 21214, 21604):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid phone number '{normalized_to}': {exc.msg}",
            )
        raise HTTPException(status_code=503, detail=f"Twilio error {exc.code}: {exc.msg}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to initiate call: {exc}")

    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "call_sid": call.sid,
        "to": normalized_to,
    }
    session.add(interaction)

    if lead:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)

    session.commit()

    logger.info("outbound call initiated", extra={
        "event": "outbound_call_initiated",
        "company_id": company_id,
        "lead_id": lead_id,
        "call_sid": call.sid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "worker_name": "dialer",
    })

    return {
        "status": "initiated",
        "call_sid": call.sid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "lead_id": lead_id,
        "user_id": actor_user.id if actor_user else actor_user_id,
    }


def execute_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
) -> dict:
    task = get_call_task_or_404(session, company_id, task_id)
    allowed, reason = is_lead_callable(session, company_id, task.lead_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=f"Lead is not callable: {reason}")

    lead = session.exec(
        select(Lead).where(
            Lead.id == task.lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    actor_id = task.assigned_user_id or actor_user_id
    return initiate_outbound_call(
        session=session,
        company_id=company_id,
        actor_user_id=actor_id,
        to=lead.normalized_phone,
        lead_id=lead.id,
        call_task_id=task.id,
    )


def schedule_retry_for_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task: CallTask,
    retry_after_hours: int,
    reason: str,
) -> CallTask:
    task.status = "retry_scheduled"
    from datetime import timedelta

    task.retry_after = utc_now() + timedelta(hours=retry_after_hours)
    task.scheduled_at = task.retry_after
    task.notes = ((task.notes or "").strip() + f"\nRetry scheduled: {reason}").strip()
    task.updated_at = utc_now()
    task.updated_by = actor_user_id
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def run_batch_dialer(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 20,
) -> list[dict]:
    # Per-minute rate limit — read from company settings (DIALER_CALLS_PER_MINUTE). Default: 10 calls/min → one call every 6 s.  Set to 0 to disable throttling.
    cpm_raw = get_company_setting_value(session, company_id, "DIALER_CALLS_PER_MINUTE")
    try:
        calls_per_minute = max(0, int(cpm_raw or 10))
    except (TypeError, ValueError):
        calls_per_minute = 10
    inter_call_delay = (60.0 / calls_per_minute) if calls_per_minute > 0 else 0.0

    results: list[dict] = []
    for call_count in range(limit):
        task = get_next_queued_task(session, company_id)
        if not task:
            break

        # Throttle: wait before firing the second and subsequent calls
        if call_count > 0 and inter_call_delay > 0:
            time.sleep(inter_call_delay)

        try:
            result = execute_call_task(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                task_id=task.id,
            )
            logger.info("call task executed", extra={
                "event": "call_task_executed",
                "company_id": company_id,
                "task_id": task.id,
                "call_sid": result.get("call_sid"),
                "worker_name": "dialer",
            })
            results.append({"success": True, "task_id": task.id, "result": result})
        except Exception as exc:
            logger.exception("call task failed", extra={
                "event": "call_task_failed",
                "company_id": company_id,
                "task_id": task.id,
                "error": str(exc),
                "worker_name": "dialer",
            })
            task.status = "failed"
            task.last_outcome = "failed"
            task.updated_at = utc_now()
            task.updated_by = actor_user_id
            session.add(task)
            session.commit()
            results.append({"success": False, "task_id": task.id, "error": str(exc)})
    return results
