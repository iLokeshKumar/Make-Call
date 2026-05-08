import os
import sys
import time
import asyncio
# On Windows, use the Selector event loop so psycopg's async code is compatible.
# Must be set before any async pools or libraries are imported/initialized.
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path, override=False)

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import settings as app_settings
from database import engine, init_db, rls_company_id
from models.models import BackgroundJob, CallStatusEvent, CallTask, Company, Interaction, IsmActivityEvent, Lead, SentimentEvent, User, utc_now
from pipelines.voice_pipeline import VoicePipeline
from routes import admin, analytics, auth, automation, call_task, campaign, feedback, quote, requirement, templates, telephony, tracking
from routes import accounts, coach, competitors, interactions, lead_import, leads, objections, products, settings as crm_settings
from routes import knowledge
from routes import agents as agent_routes
from routes import agent_tasks as agent_tasks_routes
from routes import metrics as metrics_routes
from routes import ism_rules as ism_rules_routes
from services.call.outcome_service import apply_call_outcome, classify_outcome_from_transcript
from utils.lead_utils import get_comprehensive_lead_context
from utils.logger import generate_request_id, request_id_var, setup_logger
from utils.tracing import configure_tracing
from services.call import call_status_broadcaster, sentiment_broadcaster

logger = setup_logger(__name__)


class _RequestContextMiddleware(BaseHTTPMiddleware):
    """Sets a short request ID on every HTTP request and WebSocket handshake.
    The ID is stored in a ContextVar so every logger.* call in the same
    async task automatically includes [req:<id>] without any extra plumbing.
    Also logs a single summary line per HTTP request (method, path, status, ms).
    WebSocket connections are logged on connect only — their lifetime spans
    the full call, so the same req_id threads through all pipeline log lines.
    """
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or generate_request_id()
        token = request_id_var.set(req_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = int((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = req_id

        try:
            from services.observability import record_response as _rec
            _rec(request.method, response.status_code)
        except Exception:  # noqa: BLE001
            pass

        if not request.url.path.startswith("/uploads"):
            logger.info(
                "%s %s → %d (%dms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        return response


class _RLSMiddleware(BaseHTTPMiddleware):
    """
    Extracts company_id from the Bearer JWT (without full auth validation —
    that still happens in get_current_user) and stores it in the rls_company_id
    ContextVar BEFORE any FastAPI dependency opens a DB session.

    The after_begin listener in database.py reads this ContextVar and executes
    SET LOCAL app.current_company_id = <id> so Postgres RLS policies filter rows.

    Unauthenticated paths (health check, webhooks, public quote view) leave the
    ContextVar as None, which the RLS policy treats as "bypass" — all rows visible.
    """


    _BYPASS_PREFIXES = ("/health", "/docs", "/openapi", "/redoc", "/uploads", "/static")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self._BYPASS_PREFIXES):
            return await call_next(request)

        cid = self._extract_company_id(request)
        if cid is None:
            return await call_next(request)

        token = rls_company_id.set(cid)
        try:
            return await call_next(request)
        finally:
            rls_company_id.reset(token)

    @staticmethod
    def _extract_company_id(request: Request) -> int | None:

        from auth import SESSION_COOKIE_NAME
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        if not token:
            return None
        try:
            import jwt as _jwt
            from auth import SECRET_KEY, ALGORITHM
            payload = _jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            cid = payload.get("company_id")
            return int(cid) if cid else None
        except Exception:
            return None


class _CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit-cookie CSRF protection for cookie-authenticated requests.

    The hard work is in `auth.verify_csrf_invariants` so the decision is pure
    and unit-testable. This middleware is just a dispatcher that returns the
    403 response when the invariants fail.

    Layering (in the pure function):
      1. Safe methods (GET/HEAD/OPTIONS) pass — no state change possible.
      2. Paths in CSRF_BYPASS_PREFIXES pass (login, public token routes, webhooks).
      3. No session cookie = bearer-only client = CSRF N/A (attacker can't set
         Authorization header any more than X-CSRF-Token).
      4. Otherwise: require header to match cookie via `secrets.compare_digest`.
    """

    async def dispatch(self, request: Request, call_next):
        from csrf import (
            CSRF_COOKIE_NAME,
            CSRF_HEADER_NAME,
            SESSION_COOKIE_NAME,
            verify_csrf_invariants,
        )

        ok, reason = verify_csrf_invariants(
            method=request.method,
            path=request.url.path,
            session_cookie=request.cookies.get(SESSION_COOKIE_NAME),
            csrf_cookie=request.cookies.get(CSRF_COOKIE_NAME),
            csrf_header=(
                request.headers.get(CSRF_HEADER_NAME)
                or request.headers.get(CSRF_HEADER_NAME.lower())
            ),
        )
        if not ok:
            from starlette.responses import JSONResponse
            return JSONResponse(status_code=403, content={"detail": reason})
        return await call_next(request)


def get_company_setting_value(session: Session, company_id: int, key: str) -> str | None:
    from credentials_service import get_company_setting_value as _get_value

    return _get_value(session, company_id, key)


def resolve_call_context(session: Session, user_id: str | None, lead_id: str | None) -> tuple[User | None, Lead | None]:
    """Resolve the User + Lead bound to a voice call.

    Resolution order:
      1. Explicit user_id wins.
      2. Else fall back to the lead's owner_user_id (same tenant guaranteed).

    Never picks an arbitrary first User — that would cross tenants.  Callers
    are expected to reject the WebSocket when target_user is None.
    """
    target_user = None
    lead = None

    if user_id and user_id.isdigit() and int(user_id) != 0:
        target_user = session.get(User, int(user_id))

    if lead_id and lead_id.isdigit() and int(lead_id) != 0:
        lead = session.get(Lead, int(lead_id))
        if lead and not target_user and lead.owner_user_id:
            target_user = session.get(User, lead.owner_user_id)


    if target_user and lead and target_user.company_id != lead.company_id:
        logger.warning(
            "[Pipeline] tenant mismatch user.company=%s lead.company=%s — dropping lead",
            target_user.company_id, lead.company_id,
        )
        lead = None

    return target_user, lead


def ensure_interaction(
    session: Session,
    target_user: User | None,
    lead: Lead | None,
    interaction_id: str | None,
    source: str,
) -> str:
    # Valid interaction_id provided — verify it exists and reuse it
    if interaction_id and interaction_id.isdigit() and int(interaction_id) != 0:
        existing = session.get(Interaction, int(interaction_id))
        if existing:
            return interaction_id

    # No valid id passed — find the most recent active call interaction for this lead/user to avoid creating duplicate interactions for outbound calls where the interaction_id wasn't forwarded correctly.
    query = select(Interaction).where(
        Interaction.type == "call",
        Interaction.status == "active",
    )
    if target_user:
        query = query.where(Interaction.user_id == target_user.id)
    if lead:
        query = query.where(Interaction.lead_id == lead.id)
    recent = session.exec(query.order_by(Interaction.id.desc()).limit(1)).first()
    if recent:
        return str(recent.id)

    # Nothing found — create a new interaction as last resort
    interaction = Interaction(
        company_id=target_user.company_id if target_user else (lead.company_id if lead else 0),
        lead_id=lead.id if lead else None,
        user_id=target_user.id if target_user else None,
        type="call",
        channel="call",
        direction="outbound",
        source=source,
        content="Voice Call",
        status="active",
        session_id=interaction_id,
        started_at=utc_now(),
        created_by=target_user.id if target_user else None,
        updated_by=target_user.id if target_user else None,
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)
    return str(interaction.id)


async def run_media_stream(websocket: WebSocket, source: str) -> None:
    await websocket.accept()

    # Assign a request ID for this call so all pipeline log lines are traceable
    req_id = websocket.headers.get("X-Request-ID") or generate_request_id()
    request_id_var.set(req_id)
    logger.info("WS connect [%s] source=%s", req_id, source)

    user_id = websocket.query_params.get("user_id")
    lead_id = websocket.query_params.get("lead_id")
    raw_interaction_id = websocket.query_params.get("interaction_id")
    call_task_id = websocket.query_params.get("call_task_id")

    # Twilio Media Streams strips query parameters from the wss:// URL. Context arrives in the `start` event's customParameters.  Twilio frame order is `connected` → `start` → `media` → … so we keep reading until `start` (or timeout / `media` arrives, meaning we missed it).  Buffer consumed frames so the pipeline still sees them.
    replayed_frames: list[str] = []
    if any(v in (None, "", "0") for v in (user_id, lead_id, raw_interaction_id)):
        import asyncio as _asyncio
        import json as _json
        try:
            for _ in range(5):  # cap on frames consumed
                raw = await _asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                replayed_frames.append(raw)
                try:
                    data = _json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                event = data.get("event")
                if event == "start":
                    custom = (data.get("start") or {}).get("customParameters") or {}
                    user_id = user_id or str(custom.get("user_id") or "") or None
                    lead_id = lead_id or str(custom.get("lead_id") or "") or None
                    raw_interaction_id = raw_interaction_id or str(custom.get("interaction_id") or "") or None
                    call_task_id = call_task_id or str(custom.get("call_task_id") or "") or None
                    break
                if event == "media":
                    # Already past start without seeing customParameters — shouldn't happen with current TwiML, but bail to avoid eating audio frames into the buffer.
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Pipeline] failed to read start event for context: %s", exc)

    # Replay-aware wrapper so consumed frames still reach the pipeline in order.
    if replayed_frames:
        class _ReplayWS:
            """Minimal proxy that yields buffered frames first, then delegates
            to the real websocket.  Only iter_text() is overridden; everything
            else (send_*, accept, close, query_params, headers, client_state,
            application_state) passes through to the real ws.
            """
            def __init__(self, real, frames):
                self._real = real
                self._frames = list(frames)

            async def iter_text(self):
                while self._frames:
                    yield self._frames.pop(0)
                async for msg in self._real.iter_text():
                    yield msg

            def __getattr__(self, name):
                return getattr(self._real, name)

        websocket = _ReplayWS(websocket, replayed_frames)

    with Session(engine) as session:
        target_user, lead = resolve_call_context(session, user_id, lead_id)
        # If still no user but we have an interaction_id, recover from the already-persisted Interaction row (created by /make-call in an authenticated context — same-tenant guarantee).
        if not target_user and raw_interaction_id and raw_interaction_id.isdigit() and int(raw_interaction_id) != 0:
            db_interaction = session.get(Interaction, int(raw_interaction_id))
            if db_interaction and db_interaction.user_id:
                target_user = session.get(User, db_interaction.user_id)
                if target_user and not lead and db_interaction.lead_id:
                    lead = session.get(Lead, db_interaction.lead_id)

        if not target_user:
            logger.warning(
                "[Pipeline] rejecting call: no target_user resolvable (user_id=%s lead_id=%s interaction_id=%s source=%s)",
                user_id, lead_id, raw_interaction_id, source,
            )
            await websocket.close(code=4401)
            return

        interaction_id = ensure_interaction(session, target_user, lead, raw_interaction_id, source)

        # If lead wasn't resolved from WebSocket params (e.g., lead_id=0), fetch it from the reused outbound interaction so lead context and latency logging get the correct lead_id.
        if not lead:
            try:
                db_interaction = session.get(Interaction, int(interaction_id))
                if db_interaction and db_interaction.lead_id:
                    lead = session.get(Lead, db_interaction.lead_id)
            except (ValueError, TypeError):
                pass

        lead_context = get_comprehensive_lead_context(session, lead.id) if lead else None

        company = session.get(Company, target_user.company_id) if target_user else None
        company_name = company.name if company else "Rio CRM"

        from credentials_service import get_user_setting_value
        system_prompt = (
            (
                get_user_setting_value(session, target_user.id, "SYSTEM_PROMPT")
                or get_company_setting_value(session, target_user.company_id, "SYSTEM_PROMPT")
            )
            if target_user
            else None
        ) or "You are Rio, a concise inside-sales voice assistant."

        # Append a standard closing instruction to every call so Rio always asks for verbal feedback before hanging up.
        system_prompt += (
            "\n\n### CALL CLOSING — FEEDBACK REQUEST\n"
            "Near the end of every call where the customer is engaged, before saying goodbye, "
            "ask for brief verbal feedback: "
            "'Before we wrap up — on a scale of 1 to 5, how would you rate your experience speaking with me today?' "
            "Wait for their response, thank them warmly, and then close the call naturally. "
            "If they skip or don't give a number, don't push — simply say goodbye.\n\n"
            "AMBIGUOUS RATING HANDLING: If the customer gives two numbers ('one or five'), "
            "a range ('three to four'), or anything not a single integer, do NOT assume a value. "
            "Politely ask them to pick one: 'Just to make sure I got it right — would that be a 1 or a 5?' "
            "If they still don't give a single number, do not apologize or react as if you got a low score; "
            "thank them and close the call. Their qualitative words alone are valuable."
        )

        system_prompt += (
            "\n\n### COMMUNICATION TOOL GUARDRAILS\n"
            "If the customer asks you to send details by email or WhatsApp, you must use the send_communication tool "
            "before saying the message was sent, queued, shared, or scheduled.\n"
            "Never claim that an email or WhatsApp was sent unless a tool result in this call confirms it.\n"
            "If the customer asked for both email and WhatsApp, call send_communication with both channels. "
            "Do not silently downgrade to one channel.\n"
            "After the tool returns, describe only the channels that actually succeeded or were queued. "
            "If one channel failed, say that plainly and do not imply both worked.\n"
            "If the customer is still clarifying what to send, ask one short clarification question instead of promising delivery."
        )
        system_prompt += (
            "\n\n### LIVE CALL BEHAVIOR\n"
            "Respect the configured AI_VERBOSITY level for length. Even at the highest verbosity, keep spoken replies easy to follow.\n"
            "Ask at most one question before pausing for the customer.\n"
            "Do not speak in numbered menus, multi-option lists, or long branching choices unless the customer explicitly asks for options.\n"
            "For simple confirmations, answer directly in one short sentence and stop.\n"
            "If the customer interrupts, changes topic, says 'move on', 'other product', 'get to the point', or similar, acknowledge the switch and do not repeat the previous product summary.\n"
            "If the customer asks whether you can be heard, whether you are there, or says the line dropped, answer that directly first.\n"
            "When discussing appointments, reminders, or reschedules, use the lead's local timezone from system context. If tool output or stored data is in ISO/UTC form, translate it into the lead's local time before speaking.\n"
            "Do not invent product specs, availability, comparisons, pricing, or version support from memory. Use get_product_info first when giving product details or comparing models. If the catalog does not confirm it, say you need to check.\n"
            "Never continue speaking in long multi-part lists unless the customer explicitly asked for a detailed walkthrough.\n"
            "If the customer uses slang, jokes, or off-topic phrases, do not mirror them. Reply professionally and either steer back to the request or close politely."
        )
        system_prompt += (
            "\n\n### CONVERSATIONAL PACING\n"
            "You must sound natural and unhurried. Speak at a calm, measured pace. "
            "Do NOT deliver long blocks of text. If you have a lot of information, give a 1-sentence summary first and ask if the customer wants more details. "
            "Always pause and listen after making a point. Give the customer space to speak. "
            "Avoid being aggressive or pushy; your goal is a helpful, natural conversation."
        )
        system_prompt += (
            "\n\n### FOLLOW-UP AND SCHEDULING\n"
            "Do not promise that a follow-up call, reminder, or future outreach has been scheduled unless a booking or scheduling tool result in this call confirms it.\n"
            "If no scheduling tool was used, say you can note the preference or that someone will follow up, but do not claim the event is already scheduled."
        )
        verbosity_level = (
            get_company_setting_value(session, target_user.company_id, "AI_VERBOSITY")
            if target_user
            else None
        ) or "2"
        verbosity_rules = {
            "1": "ULTRA-CONCISE: Usually one short sentence. No lists, no multiple options, no filler, no repeated restatement.",
            "2": "BALANCED: Usually 1-2 short sentences. Keep spoken replies compact, direct, and easy to interrupt.",
            "3": "DETAILED: Up to 3 short sentences when needed. Still avoid rambling, menus, and long spoken lists unless explicitly requested.",
        }
        system_prompt += f"\n\n### VERBOSITY\n{verbosity_rules.get(str(verbosity_level), verbosity_rules['2'])}"

        stt_provider = (
            get_company_setting_value(session, target_user.company_id, "STT_PROVIDER")
            if target_user
            else None
        ) or "deepgram"
        llm_provider = (
            get_company_setting_value(session, target_user.company_id, "LLM_PROVIDER")
            if target_user
            else None
        ) or "mistral"
        tts_provider = (
            get_company_setting_value(session, target_user.company_id, "TTS_PROVIDER")
            if target_user
            else None
        ) or "cartesia"

        SARVAM_LANGUAGE_CODES = {
            "hi": "hi-IN", "ta": "ta-IN", "te": "te-IN",
            "kn": "kn-IN", "mr": "mr-IN", "gu": "gu-IN",
            "bn": "bn-IN", "pa": "pa-IN", "ml": "ml-IN",
            "en": "en-IN",
        }
        lead_language = (lead.preferred_language or "en").lower().split("-")[0] if lead else "en"
        lead_language_code = SARVAM_LANGUAGE_CODES.get(lead_language, "en-IN")

        if lead_language in SARVAM_LANGUAGE_CODES and lead_language != "en":
            logger.info(
                "[Pipeline] Language override: lead=%s lang=%s → switching STT+TTS to Sarvam",
                lead.id if lead else "?", lead_language_code,
            )
            stt_provider = "sarvam"
            tts_provider = "sarvam"
            # Inject language into system prompt so LLM responds in the right language
            system_prompt = (
                f"[LANGUAGE INSTRUCTION: Respond exclusively in {lead_language_code.split('-')[0].upper()} "
                f"(language code: {lead_language_code}). Do not switch to English unless the lead does.]\n\n"
                + system_prompt
            )

        if tts_provider == "mistral":
            system_prompt += (
                "\n\n### VOICE-SAFE WORD CHOICE\n"
                "When describing products, avoid superlatives and slang that a naive "
                "content filter could misread as adult or aggressive: never use "
                "'hot', 'hottest', 'sexy', 'steamy', 'juicy', 'fire', 'killer', "
                "'sick', 'wild', 'crazy'. "
                "Prefer: 'top-selling', 'popular', 'best-rated', 'most-loved', "
                "'in-demand', 'trending', 'bestseller', 'flagship', 'standout'. "
                "This keeps speech synthesis from being blocked mid-call."
            )

        communicator = telephony.get_communicator_for_source(source, websocket)
        transcript_accumulator: list[str] = []
        pipeline = VoicePipeline(
            communicator=communicator,
            interaction_id=interaction_id,
            system_prompt=system_prompt,
            transcript_accumulator=transcript_accumulator,
            session=session,
            stt_provider=stt_provider,
            llm_provider=llm_provider,
            tts_provider=tts_provider,
            company_name=company_name,
            user=target_user,
            lead_context=lead_context,
            lead_id=lead.id if lead else None,
            lead_language=lead_language_code,
        )

        try:
            _ct_conn = (
                session.get(CallTask, int(call_task_id))
                if call_task_id and call_task_id.isdigit() and int(call_task_id) != 0
                else None
            )
            call_status_broadcaster.publish(
                company_id=target_user.company_id if target_user else 0,
                campaign_id=_ct_conn.campaign_id if _ct_conn else None,
                call_task_id=int(call_task_id) if call_task_id and call_task_id.isdigit() else None,
                interaction_id=interaction_id,
                lead_id=lead.id if lead else None,
                lead_name=lead.name if lead else None,
                status="connected",
            )
        except Exception:
            pass

        max_call_duration = app_settings.MAX_CALL_DURATION_SECONDS
        _ended_outcome: str | None = None
        call_status = "completed"
        try:
            await asyncio.wait_for(pipeline.run(), timeout=max_call_duration)
        except asyncio.TimeoutError:
            # Call exceeded max duration — treat as completed so transcript/outcome are saved normally
            logger.warning(
                "Call interaction %s exceeded max duration (%ds), terminating.",
                interaction_id,
                max_call_duration,
            )
        except Exception as exc:
            call_status = "failed"
            logger.error("Voice pipeline failed for interaction %s: %s", interaction_id, exc, exc_info=True)
        finally:
            pipeline.flush_transcript()
            db_interaction = session.get(Interaction, int(interaction_id)) if interaction_id.isdigit() else None
            if db_interaction:
                db_interaction.status = "completed" if call_status == "completed" else "failed"
                db_interaction.ended_at = utc_now()
                db_interaction.updated_by = target_user.id if target_user else None
                session.add(db_interaction)
                session.commit()

            # Skip task-update path when call_task_id is the sentinel "0" (no real CallTask — manual /make-call).  classify_outcome_from_transcript is sync (returns dict), do NOT await it.
            if call_task_id and call_task_id.isdigit() and int(call_task_id) != 0 and target_user:
                try:
                    transcript = db_interaction.transcript if db_interaction else None
                    raw_status = "completed" if call_status == "completed" else "failed"
                    outcome_confidence = None
                    if call_status == "completed" and transcript:
                        classification = classify_outcome_from_transcript(None, transcript)
                        raw_status = classification["normalized_outcome"]
                        outcome_confidence = classification.get("confidence")

                    _ended_outcome = raw_status
                    apply_call_outcome(
                        session=session,
                        company_id=target_user.company_id,
                        actor_user_id=target_user.id,
                        task_id=int(call_task_id),
                        interaction_id=int(interaction_id) if interaction_id.isdigit() else None,
                        raw_status=raw_status,
                        transcript=transcript,
                        confidence=outcome_confidence,
                    )
                except Exception as exc:
                    logger.warning("Could not update CallTask %s: %s", call_task_id, exc)

            try:
                if call_task_id and call_task_id.isdigit() and int(call_task_id) != 0 and target_user:
                    _ct_end = session.get(CallTask, int(call_task_id))
                    call_status_broadcaster.publish(
                        company_id=target_user.company_id,
                        campaign_id=_ct_end.campaign_id if _ct_end else None,
                        call_task_id=int(call_task_id),
                        interaction_id=interaction_id,
                        lead_id=lead.id if lead else None,
                        lead_name=lead.name if lead else None,
                        status="ended",
                        outcome=_ended_outcome,
                    )
            except Exception:
                pass

            # Enqueue post-call processing as a crash-safe background job. The automation worker picks this up and runs extract_and_save_requirements + dispatch_next_action. Writing the job row is synchronous and survives a FastAPI process restart — unlike an in-process asyncio.create_task.
            if db_interaction and db_interaction.lead_id and db_interaction.transcript and target_user:
                try:
                    # Deduplicate: skip if a job for this interaction is already pending or running.
                    # This prevents double-triggers (e.g. from both provider webhooks and client-side signals)
                    # from hammering the LLM and causing duplicate downstream actions.
                    from sqlalchemy import text
                    duplicate = session.exec(
                        select(BackgroundJob).where(
                            BackgroundJob.company_id == target_user.company_id,
                            BackgroundJob.job_type == "post_call_workflow",
                            BackgroundJob.status.in_(["pending", "running"]),
                        ).where(
                            text("payload->>'interaction_id' = :id").bindparams(id=str(db_interaction.id))
                        )
                    ).first()

                    if duplicate:
                        logger.info(
                            "[PostCall] Skipping duplicate background job for interaction %s (existing job id=%s status=%s)",
                            db_interaction.id, duplicate.id, duplicate.status
                        )
                    else:
                        job = BackgroundJob(
                            company_id=target_user.company_id,
                            job_type="post_call_workflow",
                            payload={
                                "interaction_id": db_interaction.id,
                                "lead_id": db_interaction.lead_id,
                                "actor_user_id": target_user.id,
                            },
                        )
                        session.add(job)
                        session.commit()
                        logger.info(
                            "[PostCall] Queued background_job id=%s for interaction %s lead %s",
                            job.id, db_interaction.id, db_interaction.lead_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to queue post-call background job for interaction %s: %s",
                        interaction_id, exc,
                    )


def _log_startup_checks() -> None:
    """Warn loudly at startup if critical API keys are missing."""
    checks = {
        "DEEPGRAM_API_KEY": "STT+TTS (Deepgram)",
        "CARTESIA_API_KEY": "TTS+STT (Cartesia)",
        "MISTRAL_API_KEY": "LLM+TTS (Mistral)",
        "OPENAI_API_KEY": "LLM (OpenAI)",
        "SARVAM_API_KEY": "STT+TTS+LLM (Sarvam)",
    }
    # LLM needs at least one key
    llm_keys = {"MISTRAL_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"}
    has_llm = any(os.getenv(k) for k in llm_keys)
    if not has_llm:
        logger.error(
            "[Startup] No LLM API key found. Set at least one of: %s",
            ", ".join(sorted(llm_keys)),
        )
    for env_var, label in checks.items():
        if env_var in llm_keys:
            continue
        if not os.getenv(env_var):
            logger.warning("[Startup] %s key not set (%s). Calls using this provider will fail.", label, env_var)

    # LangSmith tracing
    configure_tracing()

    logger.info("[Startup] Key validation complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    from services.communication.email_outbox_service import email_outbox_loop
    from services.communication.imap_poller_service import imap_poll_loop

    _log_startup_checks()
    init_db()
    enable_bg_workers = app_settings.ENABLE_BACKGROUND_WORKERS
    imap_task = None
    outbox_task = None
    if enable_bg_workers:
        imap_task = _asyncio.create_task(imap_poll_loop())
        outbox_task = _asyncio.create_task(email_outbox_loop())
    else:
        logger.warning("Background workers disabled via ENABLE_BACKGROUND_WORKERS=0")
    try:
        yield
    finally:
        for task in (imap_task, outbox_task):
            if task:
                task.cancel()


app = FastAPI(title="Multi-Tenant CRM API", lifespan=lifespan)
_process_start_time: float = time.time()
app.add_middleware(_RLSMiddleware)
app.add_middleware(_CSRFMiddleware)
app.add_middleware(_RequestContextMiddleware)


def _parse_allowed_origins() -> list[str]:
    """ALLOWED_ORIGINS is a comma-separated allowlist.

    Browsers refuse to send credentials (cookies) to a wildcard origin, so we
    must enumerate the exact origins that are allowed to call the API.
    Default: localhost:3006 (frontend dev server) so local dev still works
    out of the box.
    """
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3006")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or ["http://localhost:3006"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(admin.router)
app.include_router(automation.router)
app.include_router(accounts.router)
app.include_router(leads.router)
app.include_router(lead_import.router)
app.include_router(products.router)
app.include_router(interactions.router)
app.include_router(crm_settings.router)
app.include_router(objections.router)
app.include_router(competitors.router)
app.include_router(coach.router)
app.include_router(campaign.router)
app.include_router(quote.router)
app.include_router(requirement.router)
app.include_router(call_task.router)
app.include_router(templates.router)
app.include_router(telephony.router)
app.include_router(tracking.router)
app.include_router(feedback.router)
app.include_router(knowledge.router)
app.include_router(agent_routes.router)
app.include_router(agent_tasks_routes.router, prefix="/crm")
app.include_router(metrics_routes.router)
app.include_router(ism_rules_routes.router, prefix="/crm")
from routes import agent_analytics as agent_analytics_routes
app.include_router(agent_analytics_routes.router, prefix="/crm")

try:
    from mcp_server import get_mcp_asgi_app
    _mcp_app = get_mcp_asgi_app()
    if _mcp_app is not None:
        app.mount("/mcp", _mcp_app)
        logger.info("[MCP] Server mounted at /mcp (SSE transport)")
    else:
        logger.info("[MCP] SSE app not available — run mcp_server.py separately")
except Exception as _mcp_err:
    logger.warning("[MCP] Could not mount MCP server: %s", _mcp_err)

uploads_path = os.path.join(os.getcwd(), "uploads")
os.makedirs(uploads_path, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")


@app.get("/")
async def root():
    return {"message": "API is running"}


@app.get("/health")
async def health_check():
    
    from fastapi.responses import JSONResponse
    from database import engine
    from services.automation_worker_service import get_worker_health
    import datetime

    result: dict = {}
    degraded = False


    try:
        with Session(engine) as s:
            s.exec(select(1))
        result["db"] = "ok"
    except Exception as exc:
        result["db"] = f"error:{exc}"
        degraded = True

    # Worker health
    wh = get_worker_health()
    result.update({
        "worker_last_cycle_at":              wh.get("last_cycle_at"),
        "worker_last_cycle_status":          wh.get("last_cycle_status"),
        "worker_last_cycle_duration_seconds": wh.get("last_cycle_duration_seconds"),
        "worker_total_cycles":               wh.get("total_cycles"),
        "worker_total_failed_cycles":        wh.get("total_failed_cycles"),
        "worker_paused":                     wh.get("paused"),
    })


    if wh.get("last_cycle_status") in ("never", None) and _process_start_time and \
            time.time() - _process_start_time > 300:
        degraded = True
    if wh.get("last_cycle_status") == "partial_failure":
        # partial_failure is a warning, not hard degraded — leave status as healthy
        pass

    try:
        from services.observability import get_rate_limit_hits_last_15min
        result["mistral_429_last_15min"] = get_rate_limit_hits_last_15min()
    except Exception as exc:  # noqa: BLE001
        result["mistral_429_last_15min"] = f"error:{exc}"

    try:
        from services.rag.collections import get_or_create_collection  # noqa: F401
        # Lightweight: list collections via the in-process client.
        import chromadb
        chroma_client = chromadb.PersistentClient(path="./knowledge_base")
        chroma_client.list_collections()
        result["chroma_ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["chroma_ok"] = False
        result["chroma_error"] = str(exc)[:120]

    # Process uptime
    uptime = round(time.time() - _process_start_time) if _process_start_time else None
    result["uptime_seconds"] = uptime

    result["status"] = "degraded" if degraded else "healthy"
    result["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"

    return JSONResponse(content=result, status_code=503 if degraded else 200)


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await run_media_stream(websocket, "twilio")


@app.websocket("/exotel-media-stream")
async def exotel_media_stream(websocket: WebSocket):
    await run_media_stream(websocket, "exotel")


@app.websocket("/ws/sentiment/{interaction_id}")
async def live_sentiment(websocket: WebSocket, interaction_id: str):
    """
    Dashboard WebSocket: streams real-time sentiment updates for an active call.
    Polls the sentiment_events table every 200ms using a cursor (last_id) so
    events are visible across all uvicorn workers.
    Sends a keep-alive ping every ~30s when no new events arrive.
    """
    await websocket.accept()
    last_id = 0
    idle_ticks = 0  # 200ms ticks with no new events
    try:
        while True:
            with Session(engine) as s:
                rows = s.exec(
                    select(SentimentEvent)
                    .where(SentimentEvent.interaction_id == str(interaction_id))
                    .where(SentimentEvent.id > last_id)
                    .order_by(SentimentEvent.id)
                    .limit(20)
                ).all()
            if rows:
                for row in rows:
                    await websocket.send_json(row.payload)
                    last_id = row.id
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 150 == 0:  # ~30s: 150 × 200ms
                    await websocket.send_json({"type": "ping"})
            await asyncio.sleep(0.2)
    except Exception:
        pass


@app.websocket("/ws/call-monitor/{company_id}")
async def call_monitor(
    websocket: WebSocket,
    company_id: int,
    campaign_id: int | None = None,
):
    """
    Dashboard WebSocket: live call-status feed for a company.
    Streams CallStatusEvent rows (ringing → connected → ended) scoped to
    company_id, with an optional ?campaign_id=X filter.
    Polls every 500ms using a cursor (last_id) — works across all uvicorn workers.
    Sends {"type":"ping"} every ~30s when idle.
    """
    await websocket.accept()
    last_id = 0
    idle_ticks = 0  # 500ms ticks with no new events
    try:
        while True:
            with Session(engine) as s:
                q = (
                    select(CallStatusEvent)
                    .where(CallStatusEvent.company_id == company_id)
                    .where(CallStatusEvent.id > last_id)
                )
                if campaign_id is not None:
                    q = q.where(CallStatusEvent.campaign_id == campaign_id)
                rows = s.exec(q.order_by(CallStatusEvent.id).limit(20)).all()
            if rows:
                for row in rows:
                    await websocket.send_json({
                        "type": "call_status",
                        "call_task_id": row.call_task_id,
                        "interaction_id": row.interaction_id,
                        "campaign_id": row.campaign_id,
                        "lead_id": row.lead_id,
                        "lead_name": row.lead_name,
                        "status": row.status,
                        "outcome": row.outcome,
                        "ts": row.created_at.isoformat(),
                    })
                    last_id = row.id
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 60 == 0:  # ~30s: 60 × 500ms
                    await websocket.send_json({"type": "ping"})
            await asyncio.sleep(0.5)
    except Exception:
        pass


@app.websocket("/ws/ism-activity/{company_id}")
async def ism_activity_monitor(
    websocket: WebSocket,
    company_id: int,
):
    """Live ISM agent activity feed for a company.

    Streams IsmActivityEvent rows (dispatched_email / dispatched_whatsapp /
    dispatched_call / handoff / auto_closed_won / auto_closed_lost / skipped)
    scoped to company_id.  Cursor-based polling every 500ms for cross-worker
    visibility — same pattern as /ws/call-monitor.
    """
    await websocket.accept()
    last_id = 0
    idle_ticks = 0
    try:
        while True:
            with Session(engine) as s:
                # LEFT JOIN Lead so soft-deleted leads' activity events
                # don't surface in the live feed.  Allow null lead_id
                # (system-level events without a lead).
                rows = s.exec(
                    select(IsmActivityEvent)
                    .outerjoin(Lead, Lead.id == IsmActivityEvent.lead_id)
                    .where(IsmActivityEvent.company_id == company_id)
                    .where(IsmActivityEvent.id > last_id)
                    .where((IsmActivityEvent.lead_id.is_(None)) | (Lead.deleted_at.is_(None)))
                    .order_by(IsmActivityEvent.id)
                    .limit(20)
                ).all()
            if rows:
                for row in rows:
                    await websocket.send_json({
                        "type": "ism_activity",
                        "lead_id": row.lead_id,
                        "lead_name": row.lead_name,
                        "stage": row.stage,
                        "action": row.action,
                        "reason": row.reason,
                        "metadata": row.metadata_json or {},
                        "ts": row.created_at.isoformat(),
                    })
                    last_id = row.id
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 60 == 0:  # ~30s
                    await websocket.send_json({"type": "ping"})
            await asyncio.sleep(0.5)
    except Exception:
        pass
