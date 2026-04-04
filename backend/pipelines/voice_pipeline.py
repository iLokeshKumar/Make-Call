import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime
import re
from collections import deque
from typing import Any, Dict, List, Optional

import aiohttp
import audioop
from sqlmodel import Session, select

from models.models import CompanySetting, Interaction, LatencyLog, User, utc_now
from services.llm import get_llm_service
from services.stt import get_stt_service
from services.tts import get_tts_service
from tool_adapter import execute_mcp_tool, get_mistral_tools
from utils.encryption import decrypt_value
from utils.audio import clean_voice_text
from utils.lead_utils import get_comprehensive_lead_context

logger = logging.getLogger(__name__)


def _load_company_settings(session: Session, company_id: int | None) -> dict[str, str]:
    if not company_id:
        return {}

    settings = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == company_id)
    ).all()
    return {
        item.key: decrypt_value(item.value) if item.is_secret else item.value
        for item in settings
    }


def _resolve_setting(settings: dict[str, str], keys: list[str], hint: str):
    for key in keys:
        normalized_key = key.upper()
        value = settings.get(normalized_key) or settings.get(key)
        if value:
            logger.info(f"[Settings] {hint} resolved from company_settings.{normalized_key}")
            return value

    for key in keys:
        normalized_key = key.upper()
        env_value = os.getenv(normalized_key)
        if env_value:
            logger.info(f"[EnvVar] {hint} resolved from ${normalized_key}")
            return env_value

    logger.info(f"[Fallback] {hint} not found in company_settings or env")
    return None


class VoicePipeline:
    def __init__(self, communicator, interaction_id: str, system_prompt: str, transcript_accumulator: List[str], session: Session,
                 stt_provider: str = "deepgram", llm_provider: str = "mistral", tts_provider: str = "cartesia",
                 company_name: str = "Yexis Electronics", user: User = None, lead_context: str = None,
                 company_website: str = None, lead_id: int = None,
                 audio_encoding: str = "pcm_mulaw", audio_sample_rate: int = 8000): #made changes for exotel. specified audio_encoding and audio_sample_rate as str & int respectively.
        self.communicator = communicator
        self.interaction_id = interaction_id
        self.system_prompt = system_prompt
        self.transcript_accumulator = transcript_accumulator
        self._transcript_dirty = False
        self.session = session
        self.company_name = company_name
        self.user = user
        self.lead_context = lead_context
        self.company_website = company_website
        user_id = user.id if user else None
        self.user_id = user_id  # Store as plain int to avoid DetachedInstanceError on long sessions
        self.lead_id = lead_id  # Store directly to avoid stale session lookups in save_latency
        self.company_id = user.company_id if user else None

        company_id = user.company_id if user else None
        all_settings = _load_company_settings(session, company_id)

        self.stt_provider = stt_provider or "deepgram"
        self.llm_provider = llm_provider or "mistral"
        self.tts_provider = tts_provider or "cartesia"
        
        self.audio_encoding = audio_encoding
        self.audio_sample_rate = audio_sample_rate
        self.last_customer_speech_time = time.time()
        self.last_rio_speech_end_time = time.time()
        
        # Basic Initialization (Core loop attributes)
        self.sentence_queue = asyncio.Queue()
        self.current_tts_task = None
        self.current_llm_task = None
        self.is_rio_speaking = False
        self.tts_first_byte_time = 0.0
        self.last_tts_start_time = 0.0
        self.llm_error_count = 0 
        self.current_turn_user_text = ""
        self.pending_user_turn_text = ""
        self.pending_llm_latency = 0.0
        self.llm_dispatch_task: asyncio.Task | None = None
        self.post_stt_grace = 0.5
        self.interrupt_pending = False
        self.pause_playback = False
        self.resume_event = asyncio.Event()
        self.resume_event.set()
        self.pending_interrupt_reason: str | None = None
        self.last_rio_sentences: deque[str] = deque(maxlen=3)

        # 3. Determine specific LLM, TTS, STT keys based on provider
        # Use provider-specific keys (e.g., MISTRAL_API_KEY) or fall back to general keys
        llm_api_key = _resolve_setting(
            all_settings,
            [f"{self.llm_provider.upper()}_API_KEY", "LLM_API_KEY"],
            f"{self.llm_provider.upper()} LLM API key",
        )
        tts_api_key = _resolve_setting(
            all_settings,
            [f"{self.tts_provider.upper()}_API_KEY", "TTS_API_KEY"],
            f"{self.tts_provider.upper()} TTS API key",
        )
        stt_api_key = _resolve_setting(
            all_settings,
            [f"{self.stt_provider.upper()}_API_KEY", "STT_API_KEY"],
            f"{self.stt_provider.upper()} STT API key",
        )

        llm_model = _resolve_setting(
            all_settings,
            [f"{self.llm_provider.upper()}_MODEL", "LLM_MODEL"],
            f"{self.llm_provider.upper()} LLM model",
        )
        tts_voice = _resolve_setting(
            all_settings,
            [
                f"{self.tts_provider.upper()}_VOICE_ID",
                f"{self.tts_provider.upper()}_VOICE",
                "TTS_VOICE_ID",
            ],
            f"{self.tts_provider.upper()} TTS voice",
        )
        tts_model = _resolve_setting(
            all_settings,
            [
                f"{self.tts_provider.upper()}_TTS_MODEL",
                f"{self.tts_provider.upper()}_MODEL",
                "TTS_MODEL",
            ],
            f"{self.tts_provider.upper()} TTS model",
        )
        stt_model = _resolve_setting(
            all_settings,
            [
                f"{self.stt_provider.upper()}_STT_MODEL",
                f"{self.stt_provider.upper()}_MODEL",
                "STT_MODEL",
            ],
            f"{self.stt_provider.upper()} STT model",
        )

        now_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
        time_context = f"\n\n[SYSTEM CONTEXT]: Current Time is {now_str}. Use this to resolve relative dates like 'tomorrow' or 'next Tuesday' into ISO strings for tool calls."
        
        full_system_prompt = system_prompt + time_context
        self.llm_service = get_llm_service(self.llm_provider, full_system_prompt, api_key=llm_api_key, model=llm_model)
        self.tts_service = get_tts_service(self.tts_provider, api_key=tts_api_key, voice_id=tts_voice, model=tts_model)
        self.stt_service = get_stt_service(self.stt_provider, api_key=stt_api_key, model=stt_model)
        
        # Store keys globally on instance for reference if needed
        self.integration_keys = all_settings

        # 4. Inject pre-fetched lead/prospect context if provided at start
        if lead_context:
            self._apply_context_to_prompt(lead_context)
        
        self.last_context_type = "general"
    def _pause_playback_for_interrupt(self):
        if not self.pause_playback:
            self.pause_playback = True
            self.resume_event.clear()

    def _resume_playback_from_interrupt(self):
        if self.pause_playback:
            self.pause_playback = False
            self.resume_event.set()

    def _clear_sentence_queue(self):
        while not self.sentence_queue.empty():
            try:
                self.sentence_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _cancel_pending_llm_dispatch(self):
        if self.llm_dispatch_task and not self.llm_dispatch_task.done():
            self.llm_dispatch_task.cancel()
        self.llm_dispatch_task = None

    def _schedule_llm_dispatch(self, latency: float):
        self.pending_llm_latency = latency
        self._cancel_pending_llm_dispatch()
        if not self.pending_user_turn_text.strip():
            return
        self.llm_dispatch_task = asyncio.create_task(self._defer_llm_dispatch())

    async def _defer_llm_dispatch(self):
        try:
            await asyncio.sleep(self.post_stt_grace)
            if self.interrupt_pending:
                return
            transcript = self.pending_user_turn_text.strip()
            self.pending_user_turn_text = ""
            if not transcript:
                return
            await self._dispatch_llm(transcript, self.pending_llm_latency)
        except asyncio.CancelledError:
            return
        finally:
            self.llm_dispatch_task = None

    async def _dispatch_llm(self, transcript: str, latency: float):
        if not transcript:
            return
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
        self.current_llm_task = asyncio.create_task(
            self._process_llm_response(transcript, latency)
        )

    def _handle_false_positive_interrupt(self):
        logger.info("⏹️ False positive interruption detected. Resuming playback.")
        self.interrupt_pending = False
        self.pending_interrupt_reason = None
        self._resume_playback_from_interrupt()

    def _handle_confirmed_interrupt(self, latency: float):
        logger.info("🔄 Confirmed interruption. Restarting inference with accumulated transcripts.")
        self.interrupt_pending = False
        self.pending_interrupt_reason = None
        self._cancel_pending_llm_dispatch()
        self._clear_sentence_queue()
        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
        transcript = self.pending_user_turn_text.strip()
        self.pending_user_turn_text = ""
        self._resume_playback_from_interrupt()
        if transcript:
            asyncio.create_task(self._dispatch_llm(transcript, latency))

    def _apply_context_to_prompt(self, context: str):
        """Helper to structure and inject lead context into the LLM service."""
        prospect_context = (
            f"\n\n### [PROSPECT BACKGROUND]\n"
            f"You are ALREADY speaking to an IDENTIFIED prospect. Here is their comprehensive record:\n\n"
            f"{context}\n"
            f"--- \n"
            f"CRITICAL SALES INSTRUCTIONS:\n"
            f"1. Use only the numeric `[__META_ID__]` for backend tool calls. Do NOT mention this ID in speech.\n"
            f"2. You are 'Rio', a helpful human representative. NEVER say you have a 'record', 'lead info', or 'ID' for them.\n"
            f"3. Greet them by name naturally (e.g., 'Hi Lokesh'). Do NOT report what you know about them.\n"
            f"4. Focus on the value of our products and solving their needs, not database operations."
        )
        
        # Re-build full system prompt
        now_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
        time_context = f"\n\n[SYSTEM CONTEXT]: Current Time is {now_str}. Use this to resolve relative dates like 'tomorrow' or 'next Tuesday' into ISO strings for tool calls."
        
        full_system_prompt = self.system_prompt + time_context + prospect_context
        # Ensure llm_service is already initialized before calling this
        if hasattr(self, 'llm_service') and self.llm_service:
            self.llm_service.update_system_prompt(full_system_prompt)
        self.lead_context = context
        logger.info(f"📋 [Pipeline] Assertive lead context injected into system prompt")

    def _normalize_text(self, text: str | None) -> str:
        if not text:
            return ""
        return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()

    def _is_echo_transcript(self, transcript: str) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False
        for sentence in self.last_rio_sentences:
            candidate = self._normalize_text(sentence)
            if not candidate:
                continue
            if normalized == candidate or candidate.startswith(normalized) or normalized.startswith(candidate):
                return True
        return False

    async def _load_lead_context(self, lead_id: int):
        """Proactively loads lead context from DB and updates prompt."""
        if not lead_id or lead_id <= 0:
            return
            
        logger.info(f"🔍 [Pipeline] Proactively loading context for Lead #{lead_id}...")
        context = get_comprehensive_lead_context(self.session, lead_id)
        if context:
            self._apply_context_to_prompt(context)

    async def run(self):
        speaker_task = asyncio.create_task(self._speaker_loop())
        silence_task = asyncio.create_task(self._silence_watcher())
        audio_queue = asyncio.Queue()

        async def _ingest():
            async for data in self.communicator.receive():
                await audio_queue.put(data)
            await audio_queue.put({"event": "stop"})

        ingest_task = asyncio.create_task(_ingest())

        logger.info("⏳ Waiting for telephony stream to start...")
        try:
            while True:
                data = await asyncio.wait_for(audio_queue.get(), timeout=15.0)
                if data.get("event") == "start":
                    start_msg = data.get("start", {})
                    self.communicator.stream_sid = start_msg.get("streamSid")
                    
                    # 1. Proactively check for lead_id/interaction_id in start parameters (Twilio specific)
                    params = start_msg.get("customParameters", {})
                    stream_lead_id = params.get("lead_id")
                    stream_int_id = params.get("interaction_id")
                    
                    if stream_lead_id:
                        try:
                            lid = int(stream_lead_id)
                            # Only load if we don't already have context
                            if not self.lead_context:
                                await self._load_lead_context(lid)
                        except (ValueError, TypeError):
                            pass
                            
                    if stream_int_id:
                        self.interaction_id = stream_int_id

                    logger.info(f"🚀 [Telephony] Stream started. Sid: {self.communicator.stream_sid} | Interaction: {self.interaction_id}")
                    break
                elif data.get("event") == "stop":
                    logger.error("❌ Got stop before start. Exiting.")
                    return
        except asyncio.TimeoutError:
            logger.error("❌ Timed out waiting for start event.")
            return

        # Personalized greeting if lead context is available
        greeting = f"Hello, I'm Rio from {self.company_name}! How can I help you today?"
        if self.lead_context:
            try:
                # Extract name from "[PROSPECT DATA]\nName: XYZ, Phone: ..." format or self.lead_context
                # Since lead_utils.py builds it as "Name: {lead.name}, Phone: {lead.phone}"
                name_line = [l for l in self.lead_context.split("\n") if "Name:" in l]
                if name_line:
                    lead_name = name_line[0].split(",")[0].replace("Name: ", "").replace("[PROSPECT DATA]", "").strip()
                    if lead_name and lead_name.lower() not in ["unknown", "n/a", "none"]:
                        greeting = f"Hello {lead_name}, this is Rio from {self.company_name}! How are you doing today?"
                        logger.info(f"📞 [Personalized Greeting] Sent to {lead_name}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse lead name for greeting: {e}")
        
        await self.sentence_queue.put(greeting)
        self.transcript_accumulator.append(f"Rio: {greeting}")
        self.save_transcript()

        async def _audio_gen_from_queue():
            while True:
                data = await audio_queue.get()
                event = data.get("event")
                if event == "media":
                    yield base64.b64decode(data["media"]["payload"])
                elif event == "stop":
                    break

        # ── Two consumers of audio: barge-in detector + STT ──────────────
        # We can't use the same generator twice, so we fan-out via a second queue
        stt_queue = asyncio.Queue()
        barge_queue = asyncio.Queue()

        async def _fan_out():
            """Read raw audio once, copy to both queues."""
            async for chunk in _audio_gen_from_queue():
                await stt_queue.put(chunk)
                await barge_queue.put(chunk)
            await stt_queue.put(None)   # sentinel
            await barge_queue.put(None)

        async def _stt_gen():
            """Feed STT from stt_queue."""
            while True:
                chunk = await stt_queue.get()
                if chunk is None:
                    break
                yield chunk

        async def _barge_in_detector():
            """
            Runs parallel to STT. Detects speech onset from raw mulaw audio.
            Uses RMS energy — no API, no latency. Fires the moment customer speaks.
            """
            import audioop, struct, math
            SPEECH_RMS = 400          # tune up if echo triggers, down if misses speech
            SPEECH_FRAMES_NEEDED = 3  # ~3 consecutive 20ms frames = 60ms of speech
            SILENCE_RESET_FRAMES = 15 # frames of silence before resetting counter
            
            speech_counter = 0
            silence_counter = 0

            while True:
                chunk = await barge_queue.get()
                if chunk is None:
                    break

                # mulaw → linear16 for RMS
                try:
                    pcm = audioop.ulaw2lin(chunk, 2)
                except Exception:
                    pcm = chunk

                samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
                rms = math.sqrt(sum(s*s for s in samples) / len(samples)) if samples else 0

                if rms > SPEECH_RMS:
                    silence_counter = 0
                    speech_counter += 1
                    if speech_counter >= SPEECH_FRAMES_NEEDED:
                        if self.is_rio_speaking or not self.sentence_queue.empty():
                            logger.info(f"⚡ [Barge-in] Customer speaking (RMS:{rms:.0f}) — interrupt pending")
                            if not self.interrupt_pending:
                                self.interrupt_pending = True
                                self.pending_interrupt_reason = "customer_speaking"
                                self._pause_playback_for_interrupt()
                                self._cancel_pending_llm_dispatch()
                            await self.communicator.clear_audio_buffer()
                            speech_counter = 0
                            continue
                        logger.info(f"⚡ [Barge-in] Customer speaking (RMS:{rms:.0f}) — interrupting")
                        await self._handle_barge_in(reason="customer_speaking")
                        speech_counter = 0
                else:
                    silence_counter += 1
                    if silence_counter > SILENCE_RESET_FRAMES:
                        speech_counter = 0

        # encoding, rate = "pcm_mulaw", "8000"
        encoding, rate = self.audio_encoding, self.audio_sample_rate
        stt_start_time = time.time()
        last_final_transcript = ""
        current_turn_transcript = ""

        fan_out_task = asyncio.create_task(_fan_out())
        barge_task = asyncio.create_task(_barge_in_detector())

        try:
            async for result in self.stt_service.transcribe(_stt_gen(), encoding, rate):
                transcript = result.get("transcript", "")
                is_final = result.get("is_final", False)
                res_type = result.get("type", "transcript")

                if transcript:
                    logger.debug(f"🎤 {'FINAL' if is_final else 'Interim'}: {transcript}")
                    current_turn_transcript = transcript

                if is_final or res_type == "end_of_turn":
                    if not current_turn_transcript or current_turn_transcript == last_final_transcript:
                        continue

                    # Gate: discard echo while Rio is speaking.
                    # Skip when interrupt_pending=True — user spoke during/after barge-in
                    # and that speech must NOT be echo-gated (queue may still have stale items).
                    if not self.interrupt_pending and (self.is_rio_speaking or not self.sentence_queue.empty()):
                        logger.info(f"🔇 Echo ignored: '{current_turn_transcript}'")
                        current_turn_transcript = ""
                        continue

                    last_final_transcript = current_turn_transcript
                    logger.info(f"🎤 [STT] FINAL: {current_turn_transcript}")
                    self.last_customer_speech_time = time.time()
                    logger.info(f"⏰ [VoicePipeline] Last customer speech time: {self.last_customer_speech_time}")
                    latency = time.time() - stt_start_time

                    self.transcript_accumulator.append(f"User: {current_turn_transcript}")
                    normalized_transcript = current_turn_transcript.strip()
                    if normalized_transcript:
                        if self.pending_user_turn_text:
                            self.pending_user_turn_text = (
                                f"{self.pending_user_turn_text} {normalized_transcript}"
                            ).strip()
                        else:
                            self.pending_user_turn_text = normalized_transcript

                    if self.current_llm_task and not self.current_llm_task.done():
                        self.current_llm_task.cancel()

                    if self.interrupt_pending:
                        if not normalized_transcript or self._is_echo_transcript(normalized_transcript):
                            self._handle_false_positive_interrupt()
                        else:
                            self._handle_confirmed_interrupt(latency)
                        current_turn_transcript = ""
                        continue

                    self._schedule_llm_dispatch(latency)
                    stt_start_time = time.time()
                    current_turn_transcript = ""

        except Exception as e:
            logger.error(f"❌ [VoicePipeline] STT loop error: {e}")
        finally:
            await self.sentence_queue.put(None)
            await speaker_task
            fan_out_task.cancel()
            barge_task.cancel()
            ingest_task.cancel()
            silence_task.cancel()
            self.flush_transcript()
            logger.info(f"✅ [VoicePipeline] Call ended. Interaction ID: {self.interaction_id}")
            logger.info(f"📜 [VoicePipeline] Full Transcript: {self.transcript_accumulator}")
            logger.info("📜 Post-call transcript flush complete.")
            self._run_post_call_actions()

    async def _silence_watcher(self):
        """
        Fires ONLY when:
        1. Rio finished speaking (is_rio_speaking = False, queue empty)
        2. Customer has NOT spoken since Rio finished
        3. Silence has lasted > threshold since Rio stopped
        """
        SILENCE_THRESHOLD = 15.0  # seconds after Rio finishes speaking
        CHECK_INTERVAL = 10.0

        while True:
            await asyncio.sleep(CHECK_INTERVAL)

            # Skip if Rio is still talking or has more queued
            if self.is_rio_speaking or not self.sentence_queue.empty():
                continue

            # How long since Rio finished speaking?
            silence_since_rio_finished = time.time() - self.last_rio_speech_end_time
        
            # How long since customer last spoke?
            silence_since_customer_spoke = time.time() - self.last_customer_speech_time

            # Only fire if:
            # - Rio finished speaking > threshold ago
            # - Customer hasn't spoken since Rio finished (customer spoke BEFORE Rio finished)
            if (silence_since_rio_finished > SILENCE_THRESHOLD 
                    and self.last_customer_speech_time < self.last_rio_speech_end_time):

                if self.last_context_type == "pricing":
                    phrase = "Take your time — that's a big decision and I'm happy to walk through it."
                elif self.last_context_type == "demo":
                    phrase = "Does that answer your question, or would you like me to go deeper on any part?"
                else:
                    phrase = "Still there? Happy to answer anything."

                logger.info(f"🔔 [Silence Watcher] {silence_since_rio_finished:.1f}s since Rio finished — re-engaging")
                await self.sentence_queue.put(phrase)

                # Reset so it doesn't fire again immediately
                self.last_rio_speech_end_time = time.time()
                self.last_context_type = "general"

    # async def _silence_watcher(self):
    #     """Re-engages customer after prolonged silence with context-aware phrases."""
    #     SILENCE_THRESHOLD = 15  # seconds - reduced for proactive selling
    #     CHECK_INTERVAL = 10     # check frequently for high responsiveness

    #     while True:
    #         await asyncio.sleep(CHECK_INTERVAL)
    #         silence_duration = time.time() - self.last_customer_speech_time

    #         # Only fire if: customer is silent, Rio is NOT speaking, queue is empty
    #         if (silence_duration > SILENCE_THRESHOLD 
    #                 and not self.is_rio_speaking 
    #                 and self.sentence_queue.empty()):
            
    #             # Select phrase based on the last action context
    #             if self.last_context_type == "pricing":
    #                 phrase = "Take your time — that's a big decision and I'm happy to walk through it."
    #             elif self.last_context_type == "demo":
    #                 phrase = "Does that answer your question, or would you like me to go deeper on any part?"
    #             else:
    #                 phrase = "Still there? Happy to answer anything."
                
    #             logger.info(f"🔔 [Silence Watcher] {silence_duration:.1f}s of silence in '{self.last_context_type}' context — re-engaging")
    #             await self.sentence_queue.put(phrase)
            
    #             # Reset timer so we don't spam immediately again
    #             self.last_customer_speech_time = time.time()
                
    #             # Reset context after re-engaging to avoid repetitive phrases
    #             self.last_context_type = "general"


    async def _speaker_loop(self):
        """Continuously pulls sentences from the queue and speaks them."""
        async with aiohttp.ClientSession() as session:
            # Persistent WebSockets for specific providers
            dg_ws = None
            el_ws = None
            c_ws = None
            sv_ws = None
            
            try:
                # 1. Setup persistent connections if needed
                if self.tts_provider == "deepgram":
                    dg_api_key = self.integration_keys.get("DEEPGRAM_API_KEY")
                    if not dg_api_key:
                        logger.warning("⚠️ Deepgram API key missing; falling back to REST for TTS.")
                    else:
                        dg_voice = self.tts_service.model
                        dg_url = f"wss://api.deepgram.com/v1/speak?model={dg_voice}&encoding=mulaw&sample_rate=8000"
                        dg_headers = {"Authorization": f"Token {dg_api_key}"}
                        try:
                            dg_ws = await session.ws_connect(dg_url, headers=dg_headers)
                            logger.info(f"🎯 Deepgram TTS Persistent WebSocket Connected (model={dg_voice})")
                        except Exception as exc:
                            dg_ws = None
                            logger.error(f"❌ Deepgram TTS WebSocket connect failed: {exc}")
                
                elif self.tts_provider == "elevenlabs":
                    el_api_key = self.integration_keys.get("ELEVENLABS_API_KEY")
                    if not el_api_key:
                        logger.warning("⚠️ ElevenLabs API key missing; falling back to REST for TTS.")
                    else:
                        el_voice = self.tts_service.voice_id
                        el_model = self.tts_service.model
                        el_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{el_voice}/stream-input?model_id={el_model}&output_format=ulaw_8000"
                        el_headers = {"xi-api-key": el_api_key}
                        try:
                            el_ws = await session.ws_connect(el_url, headers=el_headers)
                            # Send BOS (beginning-of-stream) to initialize the persistent connection
                            await el_ws.send_json({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}})
                            logger.info(f"🎯 ElevenLabs TTS Persistent WebSocket Connected (voice={el_voice}, model={el_model})")
                        except Exception as exc:
                            el_ws = None
                            logger.error(f"❌ ElevenLabs TTS WebSocket connect failed: {exc}")
                elif self.tts_provider == "cartesia":
                    c_api_key = self.integration_keys.get("CARTESIA_API_KEY")
                    if not c_api_key:
                        logger.warning("⚠️ Cartesia API key missing; falling back to REST for TTS.")
                    else:
                        c_url = f"wss://api.cartesia.ai/tts/websocket?api_key={c_api_key}&cartesia_version=2025-04-16"
                        try:
                            c_ws = await session.ws_connect(c_url)
                            logger.info("🎯 Cartesia TTS Persistent WebSocket Connected (aiohttp)")
                        except Exception as exc:
                            c_ws = None
                            logger.error(f"❌ Cartesia TTS WebSocket connect failed: {exc}")

                elif self.tts_provider == "sarvam":
                    sv_api_key = self.integration_keys.get("SARVAM_API_KEY")
                    if not sv_api_key:
                        logger.warning("⚠️ Sarvam API key missing; falling back to REST for TTS.")
                    else:
                        sv_headers = {"api-subscription-key": sv_api_key}
                        from services.tts.sarvam import SarvamTTS
                        try:
                            sv_ws = await session.ws_connect(SarvamTTS.WS_URL, headers=sv_headers)
                            sv_config = SarvamTTS.ws_config_frame(
                                model=self.tts_service.model,
                                speaker=self.tts_service.speaker,
                            )
                            await sv_ws.send_str(sv_config)
                            logger.info("🎯 Sarvam TTS Persistent WebSocket Connected")
                        except Exception as exc:
                            sv_ws = None
                            logger.error(f"❌ Sarvam TTS WebSocket connect failed: {exc}")

            # 2. Main Speaker Loop
                while True:
                    await self.resume_event.wait()
                    sentence = await self.sentence_queue.get()
                    if sentence is None:
                        break

                    if not self.communicator.stream_sid:
                        logger.warning("⚠️ Speaker loop waiting for stream_sid...")
                        await asyncio.sleep(0.5)

                    if self.tts_provider == "cartesia":
                        if not c_ws or c_ws.closed:
                            c_api_key = self.integration_keys.get("CARTESIA_API_KEY")
                            if not c_api_key:
                                logger.warning("⚠️ Cartesia API key missing; cannot reopen websocket.")
                                c_ws = None
                            else:
                                c_url = f"wss://api.cartesia.ai/tts/websocket?api_key={c_api_key}&cartesia_version=2025-04-16"
                                try:
                                    c_ws = await session.ws_connect(c_url)
                                    logger.info("🎯 Cartesia TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    c_ws = None
                                    logger.error(f"❌ Cartesia TTS WebSocket reconnect failed: {exc}")

                    elif self.tts_provider == "elevenlabs":
                        if not el_ws or el_ws.closed:
                            el_api_key = self.integration_keys.get("ELEVENLABS_API_KEY")
                            if not el_api_key:
                                logger.warning("⚠️ ElevenLabs API key missing; cannot reopen websocket.")
                                el_ws = None
                            else:
                                el_voice = self.tts_service.voice_id
                                el_model = self.tts_service.model
                                el_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{el_voice}/stream-input?model_id={el_model}&output_format=ulaw_8000"
                                el_headers = {"xi-api-key": el_api_key}
                                try:
                                    el_ws = await session.ws_connect(el_url, headers=el_headers)
                                    await el_ws.send_json({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}})
                                    logger.info("🎯 ElevenLabs TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    el_ws = None
                                    logger.error(f"❌ ElevenLabs TTS WebSocket reconnect failed: {exc}")

                    elif self.tts_provider == "deepgram":
                        if not dg_ws or dg_ws.closed:
                            dg_api_key = self.integration_keys.get("DEEPGRAM_API_KEY")
                            if not dg_api_key:
                                logger.warning("⚠️ Deepgram API key missing; cannot reopen websocket.")
                                dg_ws = None
                            else:
                                dg_voice = self.tts_service.model
                                dg_url = f"wss://api.deepgram.com/v1/speak?model={dg_voice}&encoding=mulaw&sample_rate=8000"
                                dg_headers = {"Authorization": f"Token {dg_api_key}"}
                                try:
                                    dg_ws = await session.ws_connect(dg_url, headers=dg_headers)
                                    logger.info("🎯 Deepgram TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    dg_ws = None
                                    logger.error(f"❌ Deepgram TTS WebSocket reconnect failed: {exc}")

                    elif self.tts_provider == "sarvam":
                        if not sv_ws or sv_ws.closed:
                            sv_api_key = self.integration_keys.get("SARVAM_API_KEY")
                            if not sv_api_key:
                                logger.warning("⚠️ Sarvam API key missing; cannot reopen websocket.")
                                sv_ws = None
                            else:
                                sv_headers = {"api-subscription-key": sv_api_key}
                                from services.tts.sarvam import SarvamTTS
                                try:
                                    sv_ws = await session.ws_connect(SarvamTTS.WS_URL, headers=sv_headers)
                                    sv_config = SarvamTTS.ws_config_frame(
                                        model=self.tts_service.model,
                                        speaker=self.tts_service.speaker,
                                    )
                                    await sv_ws.send_str(sv_config)
                                    logger.info("🎯 Sarvam TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    sv_ws = None
                                    logger.error(f"❌ Sarvam TTS WebSocket reconnect failed: {exc}")
                
                    tts_text = clean_voice_text(sentence) if sentence else ""
                    logger.info(f"🗣️ [Speaker Loop] Starting TTS for: '{tts_text}'")
                    normalized_sentence = self._normalize_text(tts_text)
                    if normalized_sentence:
                        self.last_rio_sentences.append(normalized_sentence)
                    # Generate a unique context_id per sentence for better multiplexing
                    turn_context_id = f"ctx_{self.interaction_id}_{int(time.time()*1000)}"

                    self.is_rio_speaking = True
                    self.last_tts_start_time = time.time()

                    # For Cartesia: fire TTS request AND immediately check for next sentence
                    # Cartesia queues them server-side via context_id
                    if self.tts_provider == "cartesia" and c_ws:
                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(
                                text=tts_text,
                                communicator=self.communicator,
                                ws_to_use=c_ws,
                                context_id=turn_context_id,
                                aiohttp_session=session
                            )
                        )
                        try:
                            await self.current_tts_task
                        except asyncio.CancelledError:
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            self.is_rio_speaking = False
                            self.last_rio_speech_end_time = time.time()
                            self.sentence_queue.task_done()
                    else:
                        # Determine which persistent WS to pass as generic 'ws_to_use'
                        active_ws = None
                        if self.tts_provider == "deepgram":
                            active_ws = dg_ws
                        elif self.tts_provider == "elevenlabs":
                            active_ws = el_ws
                        elif self.tts_provider == "sarvam":
                            active_ws = sv_ws
                        # mimo is REST-based — no persistent WebSocket, active_ws stays None

                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(
                                text=tts_text,
                                communicator=self.communicator,
                                ws_to_use=active_ws,
                                context_id=turn_context_id, #if self.tts_provider == "cartesia" else None,
                                aiohttp_session=session, #if self.tts_provider == "cartesia" else None
                            )
                        )
                        try:
                            await self.current_tts_task
                        except asyncio.CancelledError:
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            self.is_rio_speaking = False
                            self.last_rio_speech_end_time = time.time()
                            self.sentence_queue.task_done()
            
            finally:
                # Cleanup persistent WebSockets
                if dg_ws: await dg_ws.close()
                if el_ws: await el_ws.close()
                if c_ws: await c_ws.close()
                if sv_ws: await sv_ws.close()

    async def _handle_barge_in(self, reason: str = "Unknown"):
        """Interrupts current AI activities."""
        logger.info(f"🛑 Barge-in! Interrupting AI. Reason: '{reason}'")
        if not self.interrupt_pending:
            self.interrupt_pending = True
            self.pending_interrupt_reason = reason
            self._pause_playback_for_interrupt()
            self._cancel_pending_llm_dispatch()
        await self.communicator.clear_audio_buffer()
        self.llm_service.clean_interrupted_tool_calls()
        self.current_turn_user_text = ""
        self.is_rio_speaking = False

    def save_latency(self, engine_name, stt, llm, tts, stt_p=None, stt_m=None, llm_p=None, llm_m=None, tts_p=None, tts_m=None):
        """Saves turn-level latency metrics to DB."""
        try:
            # Handle non-integer interaction_id (e.g., session strings)
            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None
                logger.debug(f"ℹ️ Interaction ID '{self.interaction_id}' is a session string. Saving latency as anonymous.")

            log_user_id = self.user_id
            log_lead_id = self.lead_id

            log = LatencyLog(
                company_id=self.company_id,
                interaction_id=interaction_id_int,
                user_id=log_user_id,
                lead_id=log_lead_id,
                engine=engine_name,
                stt_ms=round(stt * 1000, 2),
                llm_ms=round(llm * 1000, 2),
                tts_ms=round(tts * 1000, 2),
                total_ms=round((stt + llm + tts) * 1000, 2),
                stt_provider=stt_p,
                stt_model=stt_m,
                llm_provider=llm_p,
                llm_model=llm_m,
                tts_provider=tts_p,
                tts_model=tts_m,
                notes=f"ID: {self.interaction_id}" if interaction_id_int is None else None,
            )
            self.session.add(log)
            self.session.commit()

            # Detailed Logging (unchanged)
            logger.info(
                f"⏱️ [Latency Saved] {engine_name} | Total: {log.total_ms}ms\n"
                f"   🎙️ STT: {stt*1000:.0f}ms ({stt_p}/{stt_m})\n"
                f"   🧠 LLM: {llm*1000:.0f}ms ({llm_p}/{llm_m})\n"
                f"   🔊 TTS: {tts*1000:.0f}ms ({tts_p}/{tts_m})"
            )
        except Exception as e:
            logger.error(f"❌ Error saving latency: {e}")

    
    # def save_transcript(self, engine_name="voice_call"):
    #     """Saves transcript to Interaction table. Upserts if record exists."""
    #     try:
    #         full_transcript = "\n".join(self.transcript_accumulator)
    #         if not full_transcript.strip():
    #             return

    #         try:
    #             interaction_id_int = int(self.interaction_id)
    #         except (ValueError, TypeError):
    #             interaction_id_int = None

    #         db_i = None
    #         if interaction_id_int:
    #             db_i = self.session.get(Interaction, interaction_id_int)
            
    #         if not db_i:
    #             # Try to find a lead if we have a phone number (not implemented in VoicePipeline but good pattern)
    #             # For now, create a new Interaction record
    #             db_i = Interaction(
    #                 lead_id=0, # Anonymous lead
    #                 type="call",
    #                 content=f"Voice Interaction ({engine_name})",
    #                 transcript=full_transcript,
    #                 timestamp=datetime.now(timezone.utc),
    #                 source="Voice Call",
    #                 created_by="Rio AI"
    #             )
    #             self.session.add(db_i)
    #             self.session.commit()
    #             self.session.refresh(db_i)
    #             # If we're now assigning an ID, update our internal reference
    #             if not interaction_id_int:
    #                 self.interaction_id = str(db_i.id)
    #         else:
    #             db_i.transcript = full_transcript
    #             self.session.add(db_i)
    #             self.session.commit()
                
    #         logger.debug(f"📜 [Transcript Saved] ID: {db_i.id} | Length: {len(full_transcript)} chars")
    #     except Exception as e:
    #         logger.error(f"❌ Error saving transcript: {e}")

    def save_transcript(self, engine_name="voice_call"):
        """During call: just mark dirty. DB write is deferred to flush_transcript()."""
        self._transcript_dirty = True
        # No DB write here. transcript_accumulator already has the data in memory.

    def _build_transcript_content(self) -> str:
        return "\n".join(line for line in self.transcript_accumulator if line and line.strip())

    def flush_transcript(self, engine_name="voice_call"):
        """Called ONCE after call ends. Writes full transcript to DB using a fresh session
        to avoid stale/rolled-back session state from the long-running call."""
        if not self._transcript_dirty:
            return
        try:
            full_transcript = self._build_transcript_content()
            if not full_transcript.strip():
                return

            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None

            from database import engine as _db_engine
            from sqlmodel import Session as _Session
            with _Session(_db_engine) as fresh_session:
                db_i = None
                if interaction_id_int:
                    db_i = fresh_session.get(Interaction, interaction_id_int)

                if not db_i:
                    if not self.user_id:
                        logger.warning("No user context for transcript flush fallback; skipping.")
                        return
                    db_i = Interaction(
                        company_id=self.company_id,
                        lead_id=self.lead_id,
                        user_id=self.user_id,
                        type="call",
                        channel="call",
                        direction="outbound",
                        source="voice_pipeline",
                        content=f"Voice Interaction ({engine_name})",
                        transcript=full_transcript,
                        status="completed",
                        started_at=utc_now(),
                        ended_at=utc_now(),
                        created_by=self.user_id,
                        updated_by=self.user_id,
                    )
                    fresh_session.add(db_i)
                    fresh_session.commit()
                    fresh_session.refresh(db_i)
                    if not interaction_id_int:
                        self.interaction_id = str(db_i.id)
                else:
                    db_i.transcript = full_transcript
                    db_i.status = "completed"
                    db_i.ended_at = utc_now()
                    db_i.updated_at = utc_now()
                    db_i.updated_by = self.user_id
                    fresh_session.add(db_i)
                    fresh_session.commit()

            self._transcript_dirty = False
            logger.info(f"📜 [Transcript Flushed] ID: {interaction_id_int or 'new'} | {len(full_transcript)} chars | {len(self.transcript_accumulator)} lines")
        except Exception as e:
            logger.error(f"❌ Error flushing transcript: {e}")

    def _run_post_call_actions(self) -> None:
        """
        Triggered once after the call ends and transcript is flushed.
        Saves a structured call summary and updates lead outreach metadata.
        Runs synchronously in the pipeline teardown (non-blocking errors).
        """
        try:
            from agents.post_call_nurture import CallSummarizer, CRMUpdater
            from models.models import Lead

            # Resolve interaction_id and lead from DB.
            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None

            lead_id: int | None = None
            lead_score_normalized: float = 0.0

            if interaction_id_int:
                db_i = self.session.get(Interaction, interaction_id_int)
                if db_i:
                    lead_id = db_i.lead_id

            if lead_id:
                lead = self.session.get(Lead, lead_id)
                if lead and lead.lead_score is not None:
                    lead_score_normalized = float(lead.lead_score) / 100.0

            full_transcript = self._build_transcript_content()

            # Step 1: save structured summary interaction.
            summary = CallSummarizer.summarize_call(
                lead_id=lead_id or 0,
                transcript=full_transcript,
                icp_score=lead_score_normalized,
                sentiment="neutral",
                pain_points=[],
                questions_asked=[],
                bant_answers={},
            )
            if lead_id:
                CallSummarizer.save_summary_to_crm(lead_id, summary, company_id=self.company_id or 0, actor_user_id=self.user_id)

            # Step 2: log the completed call as a CRM interaction note.
            if lead_id:
                line_count = len(self.transcript_accumulator)
                CRMUpdater.log_interaction(
                    lead_id,
                    "call_completed",
                    f"Voice call ended. {line_count} transcript lines recorded. "
                    f"Interaction ID: {self.interaction_id}.",
                    company_id=self.company_id or 0,
                    actor_user_id=self.user_id,
                )

            logger.info(
                "[PostCall] Nurture actions complete. lead_id=%s interaction=%s",
                lead_id, self.interaction_id,
            )
        except Exception as exc:
            logger.warning("[PostCall] Post-call actions failed (non-fatal): %s", exc)

    def _strip_markdown(self, text: str) -> str:
        """Removes markdown formatting like **bold**, *italics*, and bullet points for TTS."""
        if not text:
            return ""
        # Remove bold/italics markers
        text = re.sub(r'[*_]{1,3}', '', text)
        # Remove bullet points/list markers at start of lines
        text = re.sub(r'^[\s]*[-+*][\s]+', '', text, flags=re.MULTILINE)
        # Remove hashtags for headers
        text = re.sub(r'#+\s+', '', text)
        return text.strip()

    async def _process_llm_response(self, user_input, stt_latency):
        """Handles LLM generation, tool execution, and recursive follow-ups."""
        llm_start_time = time.time()
        
        # Only add user message if this is a fresh turn, not a tool recursion
        if user_input:
            self.current_turn_user_text = user_input
            self.llm_service.add_user_message(user_input)
        
        mistral_tools = get_mistral_tools()
        
        full_reply = ""
        tool_calls = None
        
        async for chunk in self.llm_service.stream(tools=mistral_tools):
            if chunk["type"] == "sentence":
                sentence = chunk["content"]
                
                # Robust technical leakage check
                if self._is_technical_leakage(sentence):
                    logger.warning(f"🚫 [VoicePipeline] Discarding JSON-leaked sentence: {sentence[:40]}...")
                    continue
                
                # Strip markdown and technical leaks before queuing for TTS
                clean_sentence = self._strip_markdown(sentence)
                clean_sentence = self._filter_technical_speech(clean_sentence)
                
                if not clean_sentence or len(clean_sentence.strip()) < 2:
                    continue

                logger.info(f"📤 [{self.llm_provider} -> Queue] Sentence: '{clean_sentence}'")
                await self.sentence_queue.put(clean_sentence)
            elif chunk["type"] == "error":
                self.llm_error_count += 1
                if self.llm_error_count >= 3:
                    fallback_sentence = "I'm sorry, I'm experiencing persistent technical difficulties. Please try calling back in a few minutes."
                    logger.warning(f"🚨 [Smart Fallback] 3 consecutive failures. Queuing final error message.")
                else:
                    fallback_sentence = "I'm sorry, I'm having a bit of trouble with my connection. Could you repeat that?"
                    logger.info(f"🔄 [Smart Fallback] Failure #{self.llm_error_count}. Queuing retry message.")
                await self.sentence_queue.put(fallback_sentence)
                return
            elif chunk["type"] == "finished":
                self.llm_error_count = 0
                full_reply = chunk["full_reply"]
                tool_calls = chunk["tool_calls"]
            #     error_msg = chunk.get("content", "Unknown LLM Error")
            #     logger.error(f"❌ [{self.llm_provider}] Stream Error in Pipeline: {error_msg}")
                
            #     # FALLBACK: Inform the user of the connection trouble instead of staying silent
            #     self.llm_error_count += 1
                
            #     if self.llm_error_count >= 3:
            #         fallback_sentence = "I'm sorry, I'm experiencing persistent technical difficulties. Please try calling back in a few minutes."
            #         logger.warning(f"🚨 [Smart Fallback] 3 consecutive failures. Queuing final error message.")
            #     else:
            #         fallback_sentence = "I'm sorry, I'm having a bit of trouble with my connection. Could you repeat that?"
            #         logger.info(f"🔄 [Smart Fallback] Failure #{self.llm_error_count}. Queuing retry message.")
                
            #     await self.sentence_queue.put(fallback_sentence)
            #     return
            # elif chunk["type"] == "finished":
            #     # Success! Reset consecutive error count
            #     self.llm_error_count = 0
                
            #     full_reply = chunk["full_reply"]
            #     tool_calls = chunk["tool_calls"]
                reasoning_details = chunk.get("reasoning_details")
                llm_end_time = time.time()
                llm_latency = llm_end_time - llm_start_time
                
                # CRITICAL: Add assistant message ONCE with both content AND tool_calls
                # This follows OpenAI/Llama specs and prevents sequence errors
                self.llm_service.add_assistant_message(
                    full_reply, 
                    tool_calls=tool_calls, 
                    reasoning_details=reasoning_details
                )
                
                if full_reply:
                    self.transcript_accumulator.append(f"Rio: {full_reply}")
                    self.save_transcript()

                # Always save latency, even for tool-only turns
                self.save_latency(
                    f"{self.stt_provider}-{self.llm_provider}-{self.tts_provider}", 
                    stt_latency, 
                    llm_latency, 
                    self.tts_service.last_latency,
                    stt_p=self.stt_service.provider,
                    stt_m=self.stt_service.model,
                    llm_p=self.llm_service.provider,
                    llm_m=self.llm_service.model,
                    tts_p=self.tts_service.provider,
                    tts_m=self.tts_service.model
                )
                
                if tool_calls:
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        tool_args = json.loads(tc.function.arguments)
                        self.transcript_accumulator.append(f"[System]: Executing {tool_name}...")

                        # Thinking message — keep customer engaged during tool wait
                        thinking_phrases = {
                            "get_product_info":        "Let me pull up the details on that for you.",
                            "book_meeting":            "Let me get that booked for you right now.",
                            "book_demo":               "I'm scheduling that demo for you now.",
                            "send_communication":      "Sending that over to you now.",
                            "get_or_create_lead":      "One moment while I update your record.",
                            "check_icp_qualification": "Let me check if this fits your profile.",
                            "check_guardrails":        "Let me check what I can do on pricing.",
                        }
                        
                        # Update context for silence re-engagement
                        if tool_name in ["get_product_info", "check_guardrails"]:
                            self.last_context_type = "pricing"
                        elif tool_name in ["book_meeting", "book_demo"]:
                            self.last_context_type = "demo"
                        
                        thinking_msg = thinking_phrases.get(tool_name, "One moment, let me look into that for you.")
                        
                        # Only say it if Rio isn't already mid-sentence
                        if self.sentence_queue.empty() and not self.is_rio_speaking:
                            await self.sentence_queue.put(thinking_msg)
                            # Small wait so the phrase starts playing before tool execution
                            await asyncio.sleep(0.3)
                        
                        try:
                            result = await execute_mcp_tool(
                                tool_name,
                                tool_args,
                                interaction_id=self.interaction_id,
                                user_id=self.user_id,
                                user=self.user,
                                session=self.session,
                            )
                            
                            # Auto-link interaction to lead if get_or_create_lead result has lead_id
                            if tool_name == "get_or_create_lead" and "lead_id" in result:
                                try:
                                    lid = int(result["lead_id"])
                                    logger.info(f"🔗 Linking interaction {self.interaction_id} to lead {lid}")
                                    try:
                                        interaction_id_int = int(self.interaction_id)
                                        db_i = self.session.get(Interaction, interaction_id_int)
                                        if db_i:
                                            db_i.lead_id = lid
                                            self.session.add(db_i)
                                            self.session.commit()
                                    except (ValueError, TypeError):
                                        pass
                                except Exception as e:
                                    logger.error(f"❌ Failed to link interaction: {e}")

                        except asyncio.CancelledError:
                            logger.info(f"🛑 [VoicePipeline] Tool execution for '{tool_name}' interrupted by barge-in")
                            raise # Re-raise to ensure the whole turn is aborted
                        except Exception as e:
                            logger.error(f"❌ Tool Execution Error: {e}")
                            result = {"error": str(e)}
                        
                        self.llm_service.add_tool_message(tc.id, tool_name, json.dumps(result))
                    
                    logger.info("🔄 Tool results ready. Recursing for final LLM response.")
                    # Recurse with user_input=None to follow the correct tool result -> model response sequence
                    await self._process_llm_response(None, 0)
                self.current_turn_user_text = ""

    def _is_technical_leakage(self, text: str) -> bool:
        """Detects if a string looks like raw JSON, tool call fragments, or technical metadata."""
        if not text:
            return False
        
        trimmed = text.strip()
        # 1. Starts with JSON braces/brackets
        if trimmed.startswith(("{", "[", '{"', '["')):
            return True
        
        # 2. Contains key-value pair pattern (e.g. "key": "value" or "key": 123)
        if re.search(r'["\']\w+["\']\s*:\s*', trimmed):
            return True
        
        # 3. Contains tool call artifacts
        technical_terms = ['"arguments":', '"name":', '"id":', 'function_call', 'tool_calls', 'call_id']
        if any(term in trimmed for term in technical_terms):
            return True
            
        # 4. Excessive technical characters
        technical_chars = trimmed.count("{") + trimmed.count("}") + trimmed.count(":") + trimmed.count("[") + trimmed.count("]")
        if technical_chars > 3 and (":" in trimmed or "{" in trimmed):
            return True

        return False

    def _filter_technical_speech(self, text: str) -> str:
        """Regex-based safety layer to strip technical leakages from the voice stream."""
        import re
        # Catch: "lead ID 47", "ID of 47", "INTERNAL_ID", "ID is 47", "__META_ID__", etc.
        patterns = [
            r"(?i)lead\s+id\s+(?:of\s+)?\d+",
            r"(?i)internal\s+id\s+(?:of\s+)?\d+",
            r"(?i)id\s+is\s+\d+",
            r"(?i)id\s+\d+",
            r"(?i)internal\s+id",
            r"(?i)system\s+record",
            r"(?i)database\s+id",
            r"__META_ID__"
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text)
        
        # Clean up awkward double spaces or trailing conjunctions left by stripping
        text = re.sub(r"\s+", " ", text).strip()
        # Remove trailing "with a" or "and" if they were part of an ID phrase
        text = re.sub(r"\b(with a|and|for)\s*$", "", text, flags=re.IGNORECASE).strip()
        return text
    
    def get_full_transcript_self(self) -> str:
        return "\n".join(self.transcript_accumulator)

    async def _audio_generator(self, receiver):
        chunk_count = 0
        async for data in receiver:
            event = data.get("event")
            if event == "media":
                chunk_count += 1
                if chunk_count == 1:
                    logger.info("🎤 First audio chunk received from Twilio")
                yield base64.b64decode(data["media"]["payload"])
            elif event == "stop":
                logger.info("🛑 [Twilio] Stream stopped.")
                break
        logger.info(f"🎤 Audio generator finished. Total chunks: {chunk_count}")

    #async def _audio_generator(self, receiver):
    #    chunk_count = 0
    #    async for data in receiver:
    #        event = data.get("event")
    #        if event == "media":
    #            mulaw_data = base64.b64decode(data["media"]["payload"])
    #            # Convert mulaw to PCM s16le
    #            pcm_data = audioop.ulaw2lin(mulaw_data, 2)
    #            # Upsample from 8000 to 24000 Hz
    #            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, 8000, 24000, None)
    #            yield pcm_data
    #        elif event == "stop":
    #            break
