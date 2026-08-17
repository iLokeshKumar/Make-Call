"""SIP trunk communicator — bridges SIP calls into the voice pipeline.

This communicator provides a base interface for SIP trunk integration.
It follows the same pattern as Twilio/Exotel/Plivo communicators.

In production, this would be connected to a SIP.js media stream via WebSocket
or a FreeSWITCH/Kamailio bridge that converts SIP RTP into WebSocket audio.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncGenerator, Optional

from communicators.base import TelephonyCommunicator

logger = logging.getLogger(__name__)


class SIPTrunkCommunicator(TelephonyCommunicator):
    """
    SIP trunk communicator.

    Expects a WebSocket connection that delivers SIP audio as base64-encoded
    mulaw frames (matching the Twilio media format for compatibility with the
    VoicePipeline audio processing pipeline).

    Media format: mulaw 8kHz (same as Twilio) — swap to PCM s16le 16kHz if
    the SIP media gateway delivers linear audio.
    """

    def __init__(self, websocket):
        self.ws = websocket
        self.stream_sid = f"sip_{id(self)}"  # synthetic SID for pipeline compatibility

    async def receive(self) -> AsyncGenerator[dict, None]:
        """Yield events shaped like Twilio media events."""
        try:
            async for message in self.ws.iter_json():
                event = message.get("event", "media")

                if event == "start":
                    yield {
                        "event": "start",
                        "start": {
                            "streamSid": self.stream_sid,
                            "customParameters": message.get("customParameters", {}),
                        },
                    }
                elif event == "media":
                    payload = message.get("media", {}).get("payload", "")
                    if payload:
                        yield {
                            "event": "media",
                            "media": {"payload": payload},
                        }
                elif event == "stop":
                    yield {"event": "stop"}
                    break
                else:
                    logger.debug("[SIP] Unknown event: %s", event)
        except Exception as exc:
            logger.warning("[SIP] Receive error: %s", exc)
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str) -> None:
        """Send an audio chunk back through the SIP trunk."""
        try:
            await self.ws.send_json({
                "event": "media",
                "media": {"payload": b64_audio},
            })
        except Exception as exc:
            logger.warning("[SIP] send_media error: %s", exc)

    async def clear_audio_buffer(self) -> None:
        """Clear any buffered audio on the SIP gateway side."""
        try:
            await self.ws.send_json({"event": "clear"})
        except Exception:
            pass

    async def close(self) -> None:
        """Close the WebSocket connection."""
        try:
            await self.ws.close()
        except Exception:
            pass
