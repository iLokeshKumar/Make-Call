"""
TTS (Text-to-Speech) API routes for serving cloned voices.

Endpoints:
  GET  /api/tts/voices     — List available voices and cloned models
  POST /api/tts/synthesize — Generate speech from text using a selected voice
  POST /api/tts/clone      — Clone a voice from a reference WAV and synthesize
  GET  /api/tts/status     — Check TTS engine availability
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import PermissionChecker
from models.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["TTS"])

# ── Schemas ──────────────────────────────────────────────────────────────────


class VoiceInfo(BaseModel):
    id: str
    name: str
    speaker: str
    language: str
    type: str  # reference | xtts_finetuned | dataset
    source: str
    reference_wav: str | None = None
    checkpoint_path: str | None = None


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="Text to synthesize")
    voice_id: str = Field(default="xtts_finetuned", description="Voice ID from /voices")
    language: str = Field(default="en", description="Language code (en, hi, ta)")
    engine: str = Field(default="xtts", description="Engine: xtts or f5")


class SynthesizeResponse(BaseModel):
    success: bool
    audio_base64: str | None = None
    sample_rate: int | None = None
    duration: float | None = None
    error: str | None = None


class CloneRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000, description="Text to synthesize")
    reference_wav: str = Field(..., description="Path or base64-encoded WAV of reference voice")
    language: str = Field(default="en", description="Language code")
    engine: str = Field(default="xtts", description="Engine: xtts or f5")


class TTSStatus(BaseModel):
    available: bool
    xtts_python: str | None = None
    f5_available: bool = False
    voices_count: int = 0
    xtts_checkpoint: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/voices", response_model=list[VoiceInfo])
async def list_voices(
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    """List all available voices (reference WAVs, fine-tuned checkpoints, datasets)."""
    try:
        from services.ai.tts.local_tts import discover_voices
        return discover_voices()
    except ImportError as e:
        logger.warning("local_tts not available: %s", e)
        return []


@router.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize(
    request: SynthesizeRequest,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    """Generate speech from text using the selected voice."""
    try:
        from services.ai.tts.local_tts import synthesize as local_synthesize

        if request.engine not in ("xtts", "f5"):
            raise HTTPException(status_code=400, detail="Engine must be 'xtts' or 'f5'")

        result = await local_synthesize(
            text=request.text,
            voice_id=request.voice_id,
            language=request.language,
            engine=request.engine,
        )

        if not result.get("success"):
            return SynthesizeResponse(
                success=False,
                error=result.get("error", "Synthesis failed"),
            )

        return SynthesizeResponse(
            success=True,
            audio_base64=result.get("audio_base64"),
            sample_rate=result.get("sample_rate", 24000),
            duration=result.get("duration"),
        )

    except ImportError as e:
        return SynthesizeResponse(
            success=False,
            error=f"TTS service not available: {e}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("TTS synthesis error")
        return SynthesizeResponse(success=False, error=str(e))


@router.post("/clone", response_model=SynthesizeResponse)
async def clone_voice(
    request: CloneRequest,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Voice cloning: synthesize text using a custom reference WAV.

    The reference WAV can be a file path on the server or base64-encoded WAV
    data prefixed with '__b64__'.
    """
    try:
        from services.ai.tts.local_tts import synthesize as local_synthesize

        if request.engine not in ("xtts", "f5"):
            raise HTTPException(status_code=400, detail="Engine must be 'xtts' or 'f5'")

        # Save base64 reference to a temp file if needed
        ref_wav = request.reference_wav
        if ref_wav.startswith("__b64__"):
            pass  # local_tts handles this inline
        else:
            # Resolve relative to audio/ directory
            ref_path = Path(ref_wav)
            if not ref_path.is_absolute():
                audio_dir = Path(__file__).resolve().parent.parent.parent / "audio"
                candidate = audio_dir / ref_wav
                if candidate.exists():
                    ref_wav = str(candidate)
                else:
                    # Try various subdirectories
                    for sub in ["wavs", "aswini_clips", "my_voice_recordings/normalized",
                                "lk_voice_dataset_fixed/wavs", "lk_voice_dataset_chunks/wavs"]:
                        candidate = audio_dir / sub / ref_wav
                        if candidate.exists():
                            ref_wav = str(candidate)
                            break
                    else:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Reference WAV not found: {ref_wav}. "
                                   f"Use /api/tts/voices to see available files.",
                        )

        if request.engine == "f5":
            from services.ai.tts.local_tts import run_f5_inference
            result = await run_f5_inference(
                text=request.text,
                ref_audio=ref_wav,
            )
        else:
            from services.ai.tts.local_tts import run_xtts_inference
            result = await run_xtts_inference(
                text=request.text,
                speaker_wav=ref_wav,
                language=request.language,
            )

        if not result.get("success"):
            return SynthesizeResponse(
                success=False,
                error=result.get("error", "Voice cloning failed"),
            )

        return SynthesizeResponse(
            success=True,
            audio_base64=result.get("audio_base64"),
            sample_rate=result.get("sample_rate", 24000),
            duration=result.get("duration"),
        )

    except HTTPException:
        raise
    except ImportError as e:
        return SynthesizeResponse(
            success=False,
            error=f"TTS service not available: {e}",
        )
    except Exception as e:
        logger.exception("Voice cloning error")
        return SynthesizeResponse(success=False, error=str(e))


@router.get("/status", response_model=TTSStatus)
async def tts_status():
    """Check TTS engine availability and configuration."""
    from services.ai.tts.local_tts import get_xtts_python, discover_voices

    xtts_py = get_xtts_python()
    voices = discover_voices()

    # Check for F5-TTS availability
    f5_available = False
    try:
        import importlib.util
        f5_available = importlib.util.find_spec("f5_tts") is not None
    except Exception:
        pass

    # Find latest fine-tuned checkpoint
    ft_dir = Path(__file__).resolve().parent.parent.parent / "audio" / "xtts_finetuned"
    checkpoint = None
    if ft_dir.exists():
        checkpoints = sorted(ft_dir.rglob("*.pth"))
        if checkpoints:
            checkpoint = str(checkpoints[-1])

    return TTSStatus(
        available=xtts_py is not None or f5_available,
        xtts_python=xtts_py,
        f5_available=f5_available,
        voices_count=len(voices),
        xtts_checkpoint=checkpoint,
    )
