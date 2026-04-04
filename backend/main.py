import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine, init_db
from models.models import Company, Interaction, Lead, User, utc_now
from pipelines.voice_pipeline import VoicePipeline
from routes import admin, analytics, auth, automation, call_task, campaign, crm, quote, requirement, templates, telephony, tracking
from services.next_action_service import dispatch_next_action
from services.outcome_service import apply_call_outcome, classify_outcome_from_transcript
from services.post_call_service import extract_and_save_requirements
from services.llm import get_llm_service
from utils.lead_utils import get_comprehensive_lead_context
from utils.logger import setup_logger

logger = setup_logger(__name__)


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
    # 1. Valid interaction_id provided — verify it exists and reuse it
    if interaction_id and interaction_id.isdigit() and int(interaction_id) != 0:
        existing = session.get(Interaction, int(interaction_id))
        if existing:
            return interaction_id

    # 2. No valid id passed — find the most recent active call interaction
    #    for this lead/user to avoid creating duplicate interactions for
    #    outbound calls where the interaction_id wasn't forwarded correctly.
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

    # 3. Nothing found — create a new interaction as last resort
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

        # If lead wasn't resolved from WebSocket params (e.g., lead_id=0), fetch it from the
        # reused outbound interaction so lead context and latency logging get the correct lead_id.
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

        system_prompt = (
            get_company_setting_value(session, target_user.company_id, "SYSTEM_PROMPT")
            if target_user
            else None
        ) or "You are Rio, a concise inside-sales voice assistant."
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
        )

        call_status = "completed"
        try:
            await pipeline.run()
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

            if db_interaction and db_interaction.lead_id and db_interaction.transcript and target_user:
                try:
                    mistral_api_key = get_company_setting_value(session, target_user.company_id, "MISTRAL_API_KEY")
                    llm_service = get_llm_service(
                        "mistral",
                        "You extract structured B2B sales requirements from transcripts.",
                        api_key=mistral_api_key,
                    )
                    saved = await extract_and_save_requirements(
                        session=session,
                        llm_service=llm_service,
                        company_id=target_user.company_id,
                        actor_user_id=target_user.id,
                        interaction_id=db_interaction.id,
                        lead_id=db_interaction.lead_id,
                        transcript=db_interaction.transcript,
                    )
                    if saved:
                        dispatch_result = dispatch_next_action(
                            session=session,
                            company_id=target_user.company_id,
                            actor_user_id=target_user.id,
                            lead_id=db_interaction.lead_id,
                            requirement=saved,
                        )
                        logger.info("Post-call next action result: %s", dispatch_result)
                except Exception as exc:
                    logger.warning("Post-call processing failed for interaction %s: %s", interaction_id, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Multi-Tenant CRM API", lifespan=lifespan)
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
app.include_router(crm.router)
app.include_router(campaign.router)
app.include_router(quote.router)
app.include_router(requirement.router)
app.include_router(call_task.router)
app.include_router(templates.router)
app.include_router(telephony.router)
app.include_router(tracking.router)

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
