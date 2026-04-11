import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env before any other imports so os.getenv() works everywhere
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path, override=False)

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine, init_db
from models.models import BackgroundJob, Company, Interaction, Lead, SentimentEvent, User, utc_now
from pipelines.voice_pipeline import VoicePipeline
from routes import admin, analytics, auth, automation, call_task, campaign, feedback, quote, requirement, templates, telephony, tracking
from routes import accounts, coach, competitors, interactions, lead_import, leads, objections, products, settings as crm_settings
from services.outcome_service import apply_call_outcome, classify_outcome_from_transcript
from utils.lead_utils import get_comprehensive_lead_context
from utils.logger import generate_request_id, request_id_var, setup_logger
from services import sentiment_broadcaster

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
        # Skip noisy health-check / static paths from the summary log
        if not request.url.path.startswith("/uploads"):
            logger.info(
                "%s %s → %d (%dms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        return response


def get_company_setting_value(session: Session, company_id: int, key: str) -> str | None:
    from credentials_service import get_company_setting_value as _get_value

    return _get_value(session, company_id, key)


def resolve_call_context(session: Session, user_id: str | None, lead_id: str | None) -> tuple[User | None, Lead | None]:
    target_user = None
    lead = None

    if user_id and user_id.isdigit() and int(user_id) != 0:
        target_user = session.get(User, int(user_id))

    if lead_id and lead_id.isdigit() and int(lead_id) != 0:
        lead = session.get(Lead, int(lead_id))
        if lead and not target_user and lead.owner_user_id:
            target_user = session.get(User, lead.owner_user_id)

    if not target_user:
        target_user = session.exec(select(User).order_by(User.id.asc())).first()

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

    with Session(engine) as session:
        target_user, lead = resolve_call_context(session, user_id, lead_id)
        if not target_user and not lead:
            await websocket.close()
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
            "If they skip or don't give a number, don't push — simply say goodbye."
        )

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

        # Multi-language override: if lead has a preferred non-English language, then switch STT and TTS to Sarvam which supports Indian regional languages. Sarvam language codes: hi-IN, ta-IN, te-IN, kn-IN, mr-IN, gu-IN, bn-IN, pa-IN, ml-IN, en-IN
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

        max_call_duration = int(os.getenv("MAX_CALL_DURATION_SECONDS", "1800"))  # default 30 min
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

            if call_task_id and call_task_id.isdigit() and target_user:
                try:
                    transcript = db_interaction.transcript if db_interaction else None
                    raw_status = "completed" if call_status == "completed" else "failed"
                    outcome_confidence = None
                    if call_status == "completed" and transcript:
                        classification = await classify_outcome_from_transcript(None, transcript)
                        raw_status = classification["normalized_outcome"]
                        outcome_confidence = classification.get("confidence")

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

            # Enqueue post-call processing as a crash-safe background job. The automation worker picks this up and runs extract_and_save_requirements + dispatch_next_action. Writing the job row is synchronous and survives a FastAPI process restart — unlike an in-process asyncio.create_task.
            if db_interaction and db_interaction.lead_id and db_interaction.transcript and target_user:
                try:
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
        "SARVAM_API_KEY": "STT+TTS (Sarvam)",
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
    logger.info("[Startup] Key validation complete.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    from services.email_outbox_service import email_outbox_loop
    from services.imap_poller_service import imap_poll_loop

    _log_startup_checks()
    init_db()
    enable_bg_workers = os.getenv("ENABLE_BACKGROUND_WORKERS", "1").lower() in {"1", "true", "yes", "on"}
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
app.add_middleware(_RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

uploads_path = os.path.join(os.getcwd(), "uploads")
os.makedirs(uploads_path, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")


@app.get("/")
async def root():
    return {"message": "API is running"}


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
