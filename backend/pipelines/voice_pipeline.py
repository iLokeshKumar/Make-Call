import asyncio
import base64
import logging
import time
import json
from typing import List, Dict, Any, Optional

from services.llm_service import LLMService
from services.tts_service import TTSService
from services.stt_service import STTService
from utils.audio import clean_voice_text
from utils.config import async_cartesia_client, mistral_client
from tool_adapter import get_mistral_tools

logger = logging.getLogger(__name__)

class VoicePipeline:
    def __init__(self, communicator, interaction_id: str, system_prompt: str, transcript_accumulator: List[str]):
        self.communicator = communicator
        self.interaction_id = interaction_id
        self.system_prompt = system_prompt
        self.transcript_accumulator = transcript_accumulator
        
        self.llm_service = LLMService(system_prompt)
        self.tts_service = TTSService()
        self.stt_service = STTService()
        
        self.sentence_queue = asyncio.Queue()
        self.current_tts_task = None
        self.current_llm_task = None
        self.is_rio_speaking = False

    async def run(self, engine_type: str = "mistral-cartesia"):
        """
        Main loop for the voice interaction.
        """
        try:
            # 1. Start Speaker Loop
            speaker_task = asyncio.create_task(self._speaker_loop(engine_type))
            
            # 2. Initial Greeting
            greeting = "Hello, I'm Rio from Yexis Electronics! How can I help you today?"
            await self.sentence_queue.put(greeting)
            self.transcript_accumulator.append(f"Rio: {greeting}")
            
            # 3. Audio Config based on communicator/telephony
            # (Logic moved from main.py)
            encoding, rate = "pcm_mulaw", 8000 # Default for Twilio
            # if isinstance(self.communicator, Exotel): ...
            
            # 4. STT Loop
            stt_start_time = time.time()
            async for result in self.stt_service.transcribe(self._audio_generator(), engine_type, encoding, rate):
                transcript = result.get("transcript", "")
                is_final = result.get("is_final", False)
                
                if transcript and is_final:
                    logger.info(f"🎤 [STT] FINAL: {transcript}")
                    latency = time.time() - stt_start_time
                    self.transcript_accumulator.append(f"User: {transcript}")
                    
                    # Handle Barge-in
                    if self.is_rio_speaking or not self.sentence_queue.empty():
                        await self._handle_barge_in()

                    # Process response in a separate task so STT can continue
                    self.current_llm_task = asyncio.create_task(self._process_llm_response(transcript, latency, engine_type))
                    stt_start_time = time.time()

            # Signal exit
            await self.sentence_queue.put(None)
            await speaker_task

        except Exception as e:
            logger.error(f"❌ [VoicePipeline] Error: {e}")

    async def _speaker_loop(self, engine_type: str):
        """Continuously pulls sentences from the queue and speaks them."""
        # In Cartesia SDK 3.0.0, websocket_connect() takes NO config args.
        # All config (model_id, voice, output_format) goes into send(event_dict).
        async with async_cartesia_client.tts.websocket_connect() as c_ws:
            while True:
                sentence = await self.sentence_queue.get()
                if sentence is None:
                    break
                
                self.is_rio_speaking = True
                self.current_tts_task = asyncio.create_task(
                    self.tts_service.speak(sentence, engine_type, self.communicator, cartesia_ws=c_ws)
                )
                try:
                    await self.current_tts_task
                except asyncio.CancelledError:
                    logger.info("TTS Task Cancelled (Barge-in).")
                finally:
                    self.is_rio_speaking = False
                    self.sentence_queue.task_done()

    async def _handle_barge_in(self):
        """Interrupts current AI activities."""
        logger.info("🛑 Barge-in! Interrupting AI.")
        await self.communicator.clear_audio_buffer()
        
        # Clear sentence queue
        while not self.sentence_queue.empty():
            try: self.sentence_queue.get_nowait()
            except asyncio.QueueEmpty: break

        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()

    async def _process_llm_response(self, user_input, stt_latency, engine_type):
        """Handles LLM generation, tool execution, and recursive follow-ups."""
        self.llm_service.add_user_message(user_input)
        
        mistral_tools = get_mistral_tools()
        
        full_reply = ""
        tool_calls = None
        
        async for chunk in self.llm_service.stream_mistral(tools=mistral_tools):
            if chunk["type"] == "sentence":
                await self.sentence_queue.put(chunk["content"])
            elif chunk["type"] == "finished":
                full_reply = chunk["full_reply"]
                tool_calls = chunk["tool_calls"]
                
                if full_reply:
                    self.llm_service.add_assistant_message(full_reply)
                
                if tool_calls:
                    # Execute tools
                    self.llm_service.add_assistant_message(full_reply, tool_calls=tool_calls)
                    
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        tool_args = json.loads(tc.function.arguments)
                        
                        self.transcript_accumulator.append(f"[System]: Executing {tool_name}...")
                        
                        # Use the unified execute_mcp_tool
                        from ..tool_adapter import execute_mcp_tool
                        result = await execute_mcp_tool(tool_name, tool_args)
                        
                        self.llm_service.add_tool_message(tc.id, tool_name, json.dumps(result))
                    
                    # Recurse for final response after tool results
                    logger.info("🔄 Tool results ready. Recursing for final LLM response.")
                    await self._process_llm_response("Tool results ready.", 0, engine_type)

    async def _audio_generator(self):
        """Helper to yield audio chunks from the communicator."""
        async for data in self.communicator.receive():
            event = data.get("event")
            if event == "start":
                self.communicator.stream_sid = data["start"]["streamSid"]
                logger.info(f"🚀 [Twilio] Stream started. Sid: {self.communicator.stream_sid}")
            elif event == "media":
                yield base64.b64decode(data["media"]["payload"])
            elif event == "stop":
                logger.info("🛑 [Twilio] Stream stopped.")
                break
