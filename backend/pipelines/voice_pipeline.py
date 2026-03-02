import asyncio
from datetime import datetime, timezone
import base64
import logging
import time
import json
import aiohttp
import audioop
from typing import List, Dict, Any, Optional

from services.llm_service import LLMService
from services.tts_service import TTSService
from services.stt_service import STTService
from utils.audio import clean_voice_text
from utils.config import mistral_client
from tool_adapter import get_mistral_tools, execute_mcp_tool
from sqlmodel import Session
from models.models import Interaction, LatencyLog

logger = logging.getLogger(__name__)

class VoicePipeline:
    def __init__(self, communicator, interaction_id: str, system_prompt: str, transcript_accumulator: List[str], session: Session, company_name: str = "Yexis Electronics"):
        self.communicator = communicator
        self.interaction_id = interaction_id
        self.system_prompt = system_prompt
        self.transcript_accumulator = transcript_accumulator
        self.session = session
        self.company_name = company_name
        
        self.llm_service = LLMService(system_prompt)
        self.tts_service = TTSService()
        self.stt_service = STTService()
        
        self.sentence_queue = asyncio.Queue()
        self.current_tts_task = None
        self.current_llm_task = None
        self.is_rio_speaking = False
        self.tts_first_byte_time = 0.0
        self.last_tts_start_time = 0.0

    async def run(self, engine_type: str = "mistral-cartesia"):
        speaker_task = asyncio.create_task(self._speaker_loop(engine_type))
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
                    self.communicator.stream_sid = data["start"]["streamSid"]
                    logger.info(f"🚀 [Twilio] Stream started. Sid: {self.communicator.stream_sid}")
                    break
                elif data.get("event") == "stop":
                    logger.error("❌ Got stop before start. Exiting.")
                    return
        except asyncio.TimeoutError:
            logger.error("❌ Timed out waiting for Twilio start event.")
            return

        greeting = f"Hello, I'm Rio from {self.company_name}! How can I help you today?"
        await self.sentence_queue.put(greeting)
        self.transcript_accumulator.append(f"Rio: {greeting}")
        self.save_transcript()

        async def _audio_gen_from_queue():
            chunk_count = 0
            while True:
                data = await audio_queue.get()
                event = data.get("event")
                if event == "media":
                    chunk_count += 1
                    if chunk_count == 1:
                        logger.info("🎤 First audio chunk received from Twilio")
                    yield base64.b64decode(data["media"]["payload"])
                elif event == "stop":
                    logger.info(f"🛑 [Twilio] Stream stopped. Total chunks: {chunk_count}")
                    break

        encoding, rate = "pcm_mulaw", "8000"
        stt_start_time = time.time()
        last_final_transcript = ""
        current_turn_transcript = ""

        try:
            async for result in self.stt_service.transcribe(
                _audio_gen_from_queue(), engine_type, encoding, rate
            ):
                transcript = result.get("transcript", "")
                is_final = result.get("is_final", False)
                res_type = result.get("type", "transcript")

                if transcript:
                    current_turn_transcript = transcript

                if is_final or res_type == "end_of_turn":
                    if not current_turn_transcript or current_turn_transcript == last_final_transcript:
                        continue

                    last_final_transcript = current_turn_transcript
                    logger.info(f"🎤 [STT] {'🎯 EOT' if res_type == 'end_of_turn' else '✅ FINAL'}: {current_turn_transcript}")
                    latency = time.time() - stt_start_time
                    self.transcript_accumulator.append(f"User: {current_turn_transcript}")

                    if self.is_rio_speaking or not self.sentence_queue.empty():
                        await self._handle_barge_in(reason=current_turn_transcript)

                    if self.current_llm_task and not self.current_llm_task.done():
                        self.current_llm_task.cancel()
                        logger.info("♻️ Cancelled previous LLM task for new turn.")

                    self.current_llm_task = asyncio.create_task(
                        self._process_llm_response(current_turn_transcript, latency, engine_type)
                    )
                    stt_start_time = time.time()
                    current_turn_transcript = ""

        except Exception as e:
            logger.error(f"❌ [VoicePipeline] STT loop error: {e}")
        finally:
            await self.sentence_queue.put(None)
            await speaker_task
            ingest_task.cancel()

    async def _speaker_loop(self, engine_type: str):
        """Continuously pulls sentences from the queue and speaks them."""
        async with aiohttp.ClientSession() as session:
            # Persistent WebSockets for specific providers
            dg_ws = None
            el_ws = None
            c_ws = None
            
            try:
                # 1. Setup persistent connections if needed
                if engine_type == "mistral-deepgram":
                    from utils.config import DEEPGRAM_API_KEY, DEEPGRAM_VOICE
                    dg_url = f"wss://api.deepgram.com/v1/speak?model={DEEPGRAM_VOICE}&encoding=mulaw&sample_rate=8000"
                    dg_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
                    dg_ws = await session.ws_connect(dg_url, headers=dg_headers)
                    logger.info("🎯 Deepgram TTS Persistent WebSocket Connected")
                
                elif engine_type == "mistral-elevenlabs":
                    from utils.config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
                    el_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_16000"
                    el_headers = {"xi-api-key": ELEVENLABS_API_KEY}
                    el_ws = await session.ws_connect(el_url, headers=el_headers)
                    logger.info("🎯 ElevenLabs TTS Persistent WebSocket Connected")
                
                # Setup Cartesia Persistent Connection if using it
                if engine_type in ["mistral-cartesia", "mistral-deepgram-cartesia"]:
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

                    if engine_type in ["mistral-cartesia", "mistral-deepgram-cartesia"]:
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
                    if engine_type in ["mistral-cartesia", "mistral-deepgram-cartesia"] and c_ws:
                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(
                                text=sentence,
                                engine_type=engine_type,
                                communicator=self.communicator,
                                cartesia_ws=c_ws,
                                context_id=turn_context_id
                            )
                        )
                        # While Cartesia streams audio, peek at queue for next sentence
                        # and pre-send it — overlaps network+processing time
                        #self.current_tts_task = asyncio.create_task(
                            #self.tts_service.speak(
                                #text=sentence, 
                                #engine_type=engine_type, 
                                #communicator=self.communicator, 
                                #cartesia_ws=c_ws,
                                #aiohttp_session=session,
                                #deepgram_ws=dg_ws,
                                #elevenlabs_ws=el_ws,
                                #context_id=turn_context_id
                            #)
                        #)
                        try:
                            await self.current_tts_task
                        except asyncio.CancelledError:
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            self.is_rio_speaking = False
                            self.sentence_queue.task_done()
                    else:
                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(
                                text=sentence, 
                                engine_type=engine_type, 
                                communicator=self.communicator, 
                                cartesia_ws=c_ws,
                                aiohttp_session=session,
                                deepgram_ws=dg_ws,
                                elevenlabs_ws=el_ws,
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
                    timestamp=datetime.now(timezone.utc)
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

    async def _process_llm_response(self, user_input, stt_latency, engine_type):
        """Handles LLM generation, tool execution, and recursive follow-ups."""
        llm_start_time = time.time()
        self.llm_service.add_user_message(user_input)
        
        mistral_tools = get_mistral_tools()
        
        full_reply = ""
        tool_calls = None
        
        async for chunk in self.llm_service.stream_mistral(tools=mistral_tools):
            if chunk["type"] == "sentence":
                logger.info(f"📤 [Mistral -> Queue] Sentence: '{chunk['content']}'")
                await self.sentence_queue.put(chunk["content"])
            elif chunk["type"] == "finished":
                full_reply = chunk["full_reply"]
                tool_calls = chunk["tool_calls"]
                llm_end_time = time.time()
                llm_latency = llm_end_time - llm_start_time
                
                if full_reply:
                    self.llm_service.add_assistant_message(full_reply)
                    self.transcript_accumulator.append(f"Rio: {full_reply}")
                    self.save_transcript()
                    self.save_latency(
                        engine_type, 
                        stt_latency, 
                        llm_latency, 
                        self.tts_service.last_tts_latency,
                        stt_p=self.stt_service.last_provider,
                        stt_m=self.stt_service.last_model,
                        llm_p=self.llm_service.provider,
                        llm_m=self.llm_service.model,
                        tts_p=self.tts_service.last_provider,
                        tts_m=self.tts_service.last_model
                    )
                
                if tool_calls:
                    self.llm_service.add_assistant_message(full_reply, tool_calls=tool_calls)
                    
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        tool_args = json.loads(tc.function.arguments)
                        self.transcript_accumulator.append(f"[System]: Executing {tool_name}...")
                        
                        try:
                            result = await execute_mcp_tool(tool_name, tool_args)
                        except Exception as e:
                            logger.error(f"❌ Tool Execution Error: {e}")
                            result = {"error": str(e)}
                        
                        self.llm_service.add_tool_message(tc.id, tool_name, json.dumps(result))
                    
                    logger.info("🔄 Tool results ready. Recursing for final LLM response.")
                    await self._process_llm_response("Tool results ready.", 0, engine_type)

    #async def _audio_generator(self, receiver):
    #    """Helper to yield audio chunks from the communicator."""
    #    async for data in receiver:
    #        event = data.get("event")
    #        if event == "media":
    #            yield base64.b64decode(data["media"]["payload"])
    #        elif event == "stop":
    #            logger.info("🛑 [Twilio] Stream stopped.")
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