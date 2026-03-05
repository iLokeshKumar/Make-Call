import os
import logging
from datetime import datetime
import json
import re
from typing import Optional

from services.llm import get_llm_service

logger = logging.getLogger(__name__)

class DateNormalizer:
    """Uses an LLM to reliably normalize unpredictable natural language date strings."""
    
    def __init__(self, provider: str = None):
        if not provider:
            provider = os.getenv("DATE_NORMALIZER_PROVIDER", os.getenv("VOICE_ENGINE", "mistral"))
        
        # System prompt for normalization with strict business rules
        system_prompt = (
            "You are a specialized date normalization engine for a business scheduling system. "
            "Your ONLY task is to convert natural language date strings into ISO-8601 format (YYYY-MM-DDTHH:MM:SS). "
            "\n\nSTRICT RULES:\n"
            "1. ONLY FUTURE: If the input refers to a past or current time (relative to [CURRENT_TIME]), you MUST shift it to the next logical future occurrence.\n"
            "2. NO WEEKENDS: Demos cannot be scheduled on Saturday or Sunday. If the resolved date falls on a weekend, shift it to the NEXT MONDAY at the same requested time.\n"
            "3. Use the [CURRENT_TIME] provided as the absolute reference.\n"
            "4. Return ONLY the ISO string in your output, nothing else."
        )
        self.llm = get_llm_service(provider, system_prompt)

    async def normalize(self, raw_date_str: str) -> Optional[datetime]:
        """Normalize a string using AI and return a corrected datetime object."""
        if not raw_date_str:
            return None
            
        now = datetime.now()
        
        # Reset messages to only contain system prompt for a fresh stateless call
        self.llm.messages = [{"role": "system", "content": self.llm.system_prompt}]
        
        now_str = now.strftime("%A, %B %d, %Y %I:%M %p")
        prompt = f"[CURRENT_TIME]: {now_str}\n[INPUT]: '{raw_date_str}'\nISO-8601:"
        self.llm.add_user_message(prompt)
        
        try:
            full_reply = ""
            # Call stream without tools for pure text normalization
            async for chunk in self.llm.stream():
                if chunk["type"] == "finished":
                    full_reply = chunk["full_reply"].strip()
            
            # Extract just the ISO string from the reply
            iso_match = re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', full_reply)
            if iso_match:
                iso_str = iso_match.group(0)
                dt = datetime.fromisoformat(iso_str)
                # Apply SECOND LAYER of validation via code logic
                dt = self._enforce_business_rules(dt, now)
                
                logger.info(f"🧠 [AI Normalizer] Resolved '{raw_date_str}' to: {dt.isoformat()}")
                return dt
            else:
                logger.warning(f"⚠️ [AI Normalizer] Model returned non-ISO response: {full_reply}")
                return None
                
        except Exception as e:
            logger.error(f"❌ [AI Normalizer] Error: {e}")
            return None

    def _enforce_business_rules(self, dt: datetime, now: datetime) -> datetime:
        """Post-parsing validation to strictly ensure only future weekdays are booked."""
        original_dt = dt
        
        # 1. Rule: Only Future (Strictly)
        if dt <= now:
            # If it's in the past, shift to tomorrow same time
            dt = dt + timedelta(days=1)
            # Re-check if still in the past (e.g. if now is afternoon and user said 9 AM)
            if dt <= now:
                dt = dt + timedelta(days=1)
            logger.info(f"🔄 [DateNormalizer] Shifting Past/Today to Future: {original_dt} -> {dt}")

        # 2. Rule: Avoid Weekends (5=Saturday, 6=Sunday)
        while dt.weekday() >= 5:
            logger.info(f"🔄 [DateNormalizer] {dt.strftime('%A')} is a weekend. Shifting to Monday.")
            dt = dt + timedelta(days=1)
            
        return dt

# Singleton instance
_normalizer = None

async def normalize_date_ai(raw_str: str, provider: str = None) -> Optional[datetime]:
    global _normalizer
    if _normalizer is None:
        _normalizer = DateNormalizer(provider=provider)
    return await _normalizer.normalize(raw_str)