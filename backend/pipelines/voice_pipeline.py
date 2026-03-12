import asyncio
import re
from datetime import datetime, timezone
import base64
import logging
import time
import json
import aiohttp
import audioop
from typing import List, Dict, Any, Optional

from services.llm import get_llm_service
from services.tts import get_tts_service
from services.stt import get_stt_service
from utils.audio import clean_voice_text
from utils.config import mistral_client
from tool_adapter import get_mistral_tools, execute_mcp_tool
from sqlmodel import Session
from models.models import Interaction, LatencyLog, User, Lead
from utils.lead_utils import get_comprehensive_lead_context

logger = logging.getLogger(__name__)

class VoicePipeline:
    def __init__(self, communicator, interaction_id: str, system_prompt: str, transcript_accumulator: List[str], session: Session, 
                 stt_provider: str = "deepgram", llm_provider: str = "mistral", tts_provider: str = "cartesia",
                 company_name: str = "Yexis Electronics", user: User = None, lead_context: str = None,
                 company_website: str = None,
                 audio_encoding: str = "pcm_mulaw", audio_sample_rate: int = 8000): #made changes for exotel. specified audio_encoding and audio_sample_rate as str & int respectively.
        self.communicator = communicator
        self.interaction_id = interaction_id
        self.system_prompt = system_prompt
        self.transcript_accumulator = transcript_accumulator
        self.session = session
        self.company_name = company_name
        self.user = user
        self.lead_context = lead_context
        self.company_website = company_website
        self.stt_provider = stt_provider
        self.llm_provider = llm_provider
        self.tts_provider = tts_provider
        self.audio_encoding = audio_encoding
        self.audio_encoding = audio_encoding
        self.audio_sample_rate = audio_sample_rate
        
        # 1. Basic Initialization (Core loop attributes)
        self.sentence_queue = asyncio.Queue()
        self.current_tts_task = None
        self.current_llm_task = None
        self.is_rio_speaking = False
        self.tts_first_byte_time = 0.0
        self.last_tts_start_time = 0.0

        # 2. Service Initialization (LLM, TTS, STT)
        now_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")
        time_context = f"\n\n[SYSTEM CONTEXT]: Current Time is {now_str}. Use this to resolve relative dates like 'tomorrow' or 'next Tuesday' into ISO strings for tool calls."
        
        full_system_prompt = system_prompt + time_context
        self.llm_service = get_llm_service(llm_provider, full_system_prompt)
        self.tts_service = get_tts_service(tts_provider)
        self.stt_service = get_stt_service(stt_provider)

        # 3. Inject pre-fetched lead/prospect context if provided at start
        if lead_context:
            self._apply_context_to_prompt(lead_context)
        
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
                        # Customer is speaking — interrupt Rio if she's talking
                        if self.is_rio_speaking or not self.sentence_queue.empty():
                            logger.info(f"⚡ [Barge-in] Customer speaking (RMS:{rms:.0f}) — interrupting")
                            await self._handle_barge_in(reason="customer_speaking")
                            speech_counter = 0  # reset after firing
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

                    # Gate: discard echo while Rio is speaking
                    if self.is_rio_speaking or not self.sentence_queue.empty():
                        logger.info(f"🔇 Echo ignored: '{current_turn_transcript}'")
                        current_turn_transcript = ""
                        continue

                    last_final_transcript = current_turn_transcript
                    logger.info(f"🎤 [STT] FINAL: {current_turn_transcript}")
                    latency = time.time() - stt_start_time

                    self.transcript_accumulator.append(f"User: {current_turn_transcript}")

                    if self.current_llm_task and not self.current_llm_task.done():
                        self.current_llm_task.cancel()

                    self.current_llm_task = asyncio.create_task(
                        self._process_llm_response(current_turn_transcript, latency)
                    )
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

    async def _speaker_loop(self):
        """Continuously pulls sentences from the queue and speaks them."""
        async with aiohttp.ClientSession() as session:
            # Persistent WebSockets for specific providers
            dg_ws = None
            el_ws = None
            c_ws = None
            
            try:
                # 1. Setup persistent connections if needed
                if self.tts_provider == "deepgram":
                    from utils.config import DEEPGRAM_API_KEY, DEEPGRAM_VOICE
                    dg_url = f"wss://api.deepgram.com/v1/speak?model={DEEPGRAM_VOICE}&encoding=mulaw&sample_rate=8000"
                    dg_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
                    dg_ws = await session.ws_connect(dg_url, headers=dg_headers)
                    logger.info("🎯 Deepgram TTS Persistent WebSocket Connected")
                
                elif self.tts_provider == "elevenlabs":
                    from utils.config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
                    el_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_16000"
                    el_headers = {"xi-api-key": ELEVENLABS_API_KEY}
                    el_ws = await session.ws_connect(el_url, headers=el_headers)
                    logger.info("🎯 ElevenLabs TTS Persistent WebSocket Connected")
                
                # Setup Cartesia Persistent Connection if using it
                if self.tts_provider == "cartesia":
                    from utils.config import CARTESIA_API_KEY
                    c_url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}&cartesia_version=2025-04-16"
                    c_ws = await session.ws_connect(c_url)
                    logger.info("🎯 Cartesia TTS Persistent WebSocket Connected (aiohttp)")

                # 2. Main Speaker Loop
                while True:
                    sentence = await self.sentence_queue.get()
                    if sentence is None:
                        break
                    
                    if not self.communicator.stream_sid:
                        logger.warning("⚠️ Speaker loop waiting for stream_sid...")
                        await asyncio.sleep(0.5)

                    if self.tts_provider == "cartesia":
                        if not c_ws or c_ws.closed:
                            from utils.config import CARTESIA_API_KEY
                            c_url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}&cartesia_version=2025-04-16"
                            c_ws = await session.ws_connect(c_url)
                            logger.info("🎯 Cartesia TTS Persistent WebSocket (Re)Connected")

                    logger.info(f"🗣️ [Speaker Loop] Starting TTS for: '{sentence}'")
                    # Generate a unique context_id per sentence for better multiplexing
                    turn_context_id = f"ctx_{self.interaction_id}_{int(time.time()*1000)}"
                    
                    self.is_rio_speaking = True
                    self.last_tts_start_time = time.time()

                    # For Cartesia: fire TTS request AND immediately check for next sentence
                    # Cartesia queues them server-side via context_id
                    if self.tts_provider == "cartesia" and c_ws:
                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(
                                text=sentence,
                                communicator=self.communicator,
                                ws_to_use=c_ws,
                                context_id=turn_context_id
                            )
                        )
                        try:
                            await self.current_tts_task
                        except asyncio.CancelledError:
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            self.is_rio_speaking = False
                            self.sentence_queue.task_done()
                    else:
                        # Determine which persistent WS to pass as generic 'ws_to_use'
                        active_ws = None
                        if self.tts_provider == "deepgram": active_ws = dg_ws
                        elif self.tts_provider == "elevenlabs": active_ws = el_ws

                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(
                                text=sentence, 
                                communicator=self.communicator, 
                                ws_to_use=active_ws,
                                aiohttp_session=session,
                                context_id=turn_context_id
                            )
                        )
                        try:
                            await self.current_tts_task
                        except asyncio.CancelledError:
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            self.is_rio_speaking = False
                            self.sentence_queue.task_done() 
            
            finally:
                # Cleanup persistent WebSockets
                if dg_ws: await dg_ws.close()
                if el_ws: await el_ws.close()
                if c_ws: await c_ws.close()

    async def _handle_barge_in(self, reason: str = "Unknown"):
        """Interrupts current AI activities."""
        logger.info(f"🛑 Barge-in! Interrupting AI. Reason: '{reason}'")
        await self.communicator.clear_audio_buffer()
        
        # Clear sentence queue
        while not self.sentence_queue.empty():
            try: self.sentence_queue.get_nowait()
            except asyncio.QueueEmpty: break

        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()

    def save_latency(self, engine_name, stt, llm, tts, stt_p=None, stt_m=None, llm_p=None, llm_m=None, tts_p=None, tts_m=None):
        """Saves turn-level latency metrics to DB."""
        try:
            # Handle non-integer interaction_id (e.g., session strings)
            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None
                logger.debug(f"ℹ️ Interaction ID '{self.interaction_id}' is a session string. Saving latency as anonymous.")

            log = LatencyLog(
                interaction_id=interaction_id_int,
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
                notes=f"ID: {self.interaction_id}" if interaction_id_int is None else None
            )
            self.session.add(log)
            self.session.commit()
            
            # Detailed Logging
            logger.info(
                f"⏱️ [Latency Saved] {engine_name} | Total: {log.total_ms}ms\n"
                f"   🎙️ STT: {stt*1000:.0f}ms ({stt_p}/{stt_m})\n"
                f"   🧠 LLM: {llm*1000:.0f}ms ({llm_p}/{llm_m})\n"
                f"   🔊 TTS: {tts*1000:.0f}ms ({tts_p}/{tts_m})"
            )
        except Exception as e:
            logger.error(f"❌ Error saving latency: {e}")

    def save_transcript(self, engine_name="voice_call"):
        """Saves transcript to Interaction table. Upserts if record exists."""
        try:
            full_transcript = "\n".join(self.transcript_accumulator)
            if not full_transcript.strip():
                return

            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None

            db_i = None
            if interaction_id_int:
                db_i = self.session.get(Interaction, interaction_id_int)
            
            if not db_i:
                # Try to find a lead if we have a phone number (not implemented in VoicePipeline but good pattern)
                # For now, create a new Interaction record
                db_i = Interaction(
                    lead_id=0, # Anonymous lead
                    type="call",
                    content=f"Voice Interaction ({engine_name})",
                    transcript=full_transcript,
                    timestamp=datetime.now(timezone.utc),
                    source="Voice Call",
                    created_by="Rio AI"
                )
                self.session.add(db_i)
                self.session.commit()
                self.session.refresh(db_i)
                # If we're now assigning an ID, update our internal reference
                if not interaction_id_int:
                    self.interaction_id = str(db_i.id)
            else:
                db_i.transcript = full_transcript
                self.session.add(db_i)
                self.session.commit()
                
            logger.debug(f"📜 [Transcript Saved] ID: {db_i.id} | Length: {len(full_transcript)} chars")
        except Exception as e:
            logger.error(f"❌ Error saving transcript: {e}")

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
            self.llm_service.add_user_message(user_input)
        
        mistral_tools = get_mistral_tools()
        
        full_reply = ""
        tool_calls = None
        
        async for chunk in self.llm_service.stream(tools=mistral_tools):
            if chunk["type"] == "sentence":
                sentence = chunk["content"]
                # Skip sentences that are obviously raw JSON or tool call artifacts
                if sentence.strip().startswith("{") or '"arguments":' in sentence or '"name":' in sentence:
                    logger.warning(f"🚫 [VoicePipeline] Discarding JSON-leaked sentence: {sentence[:30]}...")
                    continue
                
                # Strip markdown and technical leaks before queuing for TTS
                clean_sentence = self._strip_markdown(sentence)
                clean_sentence = self._filter_technical_speech(clean_sentence)
                
                if not clean_sentence or len(clean_sentence.strip()) < 2:
                    continue

                logger.info(f"📤 [{self.llm_provider} -> Queue] Sentence: '{clean_sentence}'")
                await self.sentence_queue.put(clean_sentence)
            elif chunk["type"] == "error":
                logger.error(f"❌ [{self.llm_provider}] Stream Error in Pipeline: {chunk.get('content')}")
                return
            elif chunk["type"] == "finished":
                full_reply = chunk["full_reply"]
                tool_calls = chunk["tool_calls"]
                llm_end_time = time.time()
                llm_latency = llm_end_time - llm_start_time
                
                # CRITICAL: Add assistant message ONCE with both content AND tool_calls
                # This follows OpenAI/Llama specs and prevents sequence errors
                self.llm_service.add_assistant_message(full_reply, tool_calls=tool_calls)
                
                if full_reply:
                    self.transcript_accumulator.append(f"Rio: {full_reply}")
                    self.save_transcript()
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
                        
                        try:
                            result = await execute_mcp_tool(tool_name, tool_args, user=self.user)
                            
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

                        except Exception as e:
                            logger.error(f"❌ Tool Execution Error: {e}")
                            result = {"error": str(e)}
                        
                        self.llm_service.add_tool_message(tc.id, tool_name, json.dumps(result))
                    
                    logger.info("🔄 Tool results ready. Recursing for final LLM response.")
                    # Recurse with user_input=None to follow the correct tool result -> model response sequence
                    await self._process_llm_response(None, 0)

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
    #            break

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