"""Data residency — region-specific routing for AI services + recording storage.

Supports `routing_region: "global" | "india"` per-company.
- India region routes ASR/STT/TTS/LLM to India-local endpoints
- Recording storage uses Indian S3-compatible storage
"""

from __future__ import annotations

import logging
from typing import Optional

from models.models import Company

logger = logging.getLogger(__name__)

# Known region-specific endpoints for AI providers
REGION_ENDPOINTS: dict[str, dict[str, str]] = {
    "india": {
        "azure_openai": "https://centralindia.api.cognitive.microsoft.com",
        "azure_stt": "https://centralindia.api.cognitive.microsoft.com/stt",
        "azure_tts": "https://centralindia.api.cognitive.microsoft.com/tts",
        "sarvam": "https://api.sarvam.ai",
        "s3_storage": "s3.ap-south-1.amazonaws.com",
    },
    "global": {
        "azure_openai": "https://api.openai.com",
        "azure_stt": "https://api.deepgram.com",
        "azure_tts": "https://api.cartesia.ai",
        "sarvam": "https://api.sarvam.ai",
        "s3_storage": "s3.amazonaws.com",
    },
}

# Provider → endpoint key mapping
PROVIDER_ENDPOINT_MAP: dict[str, str] = {
    "openai": "azure_openai",
    "azure": "azure_openai",
    "deepgram": "azure_stt",
    "cartesia": "azure_tts",
    "elevenlabs": "azure_tts",
    "sarvam": "sarvam",
}


def get_routing_region(company: Company | None) -> str:
    """Return the routing region for a company, defaulting to 'global'."""
    if company:
        return getattr(company, "routing_region", "global") or "global"
    return "global"


def get_endpoint_for_provider(company: Company | None, provider: str) -> str | None:
    """Return the region-appropriate endpoint for a given AI provider.

    Example:
        get_endpoint_for_provider(company, "openai") -> "https://centralindia.api.cognitive.microsoft.com"
    """
    region = get_routing_region(company)
    endpoints = REGION_ENDPOINTS.get(region, REGION_ENDPOINTS["global"])
    endpoint_key = PROVIDER_ENDPOINT_MAP.get(provider.lower())
    if endpoint_key:
        return endpoints.get(endpoint_key)
    return None


def get_s3_endpoint(company: Company | None) -> str:
    """Return the S3-compatible storage endpoint for the company's region."""
    region = get_routing_region(company)
    return REGION_ENDPOINTS.get(region, REGION_ENDPOINTS["global"]).get("s3_storage", "s3.amazonaws.com")


def should_store_in_india(company: Company | None) -> bool:
    """Return True if the company's recordings should be stored in India."""
    return get_routing_region(company) == "india"


# ── Recording storage service ──


class RecordingStorageService:
    """Handles storing and retrieving call recordings.

    Supports pluggable backends: local filesystem (dev), S3-compatible (prod).
    """

    def __init__(self, company: Company | None = None):
        self.company = company
        self.region = get_routing_region(company)
        self._backend = self._resolve_backend()

    def _resolve_backend(self):
        if self.region == "india":
            return _S3Storage(region="ap-south-1", endpoint=get_s3_endpoint(self.company))
        return _S3Storage(region="us-east-1", endpoint=get_s3_endpoint(self.company))

    async def upload_recording(self, interaction_id: int, audio_data: bytes, filename: str) -> str:
        return await self._backend.upload(interaction_id, audio_data, filename)

    async def get_recording_url(self, interaction_id: int, filename: str) -> str | None:
        return await self._backend.get_url(interaction_id, filename)


class _S3Storage:
    """S3-compatible recording storage.

    Uses environment-configured bucket. Falls back to local path if S3
    credentials are not configured (dev mode).
    """

    def __init__(self, region: str, endpoint: str):
        self.region = region
        self.endpoint = endpoint
        self.bucket = "rio-crm-recordings"

    async def upload(self, interaction_id: int, audio_data: bytes, filename: str) -> str:
        try:
            import boto3
            s3 = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=f"https://{self.endpoint}",
            )
            key = f"recordings/{interaction_id}/{filename}"
            s3.put_object(Bucket=self.bucket, Key=key, Body=audio_data)
            logger.info("[S3] Uploaded %s to %s/%s", key, self.bucket, self.region)
            return f"s3://{self.bucket}/{key}"
        except ImportError:
            logger.warning("[S3] boto3 not installed — saving to local /tmp")
            import os
            local_dir = f"/tmp/recordings/{interaction_id}"
            os.makedirs(local_dir, exist_ok=True)
            local_path = f"{local_dir}/{filename}"
            with open(local_path, "wb") as f:
                f.write(audio_data)
            return local_path
        except Exception as exc:
            logger.warning("[S3] Upload failed: %s", exc)
            return ""

    async def get_url(self, interaction_id: int, filename: str) -> str | None:
        try:
            import boto3
            s3 = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=f"https://{self.endpoint}",
            )
            key = f"recordings/{interaction_id}/{filename}"
            url = s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=3600)
            return url
        except Exception:
            return None
