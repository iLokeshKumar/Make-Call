import re
import logging

logger = logging.getLogger(__name__)

def clean_voice_text(text: str, max_chars: int = 300) -> str:
    """Removes markdown and truncates text for voice output."""
    if not text:
        return ""
    
    # Remove markdown bold/italic/headers/separators
    text = re.sub(r'[*#_~`>]', '', text)
    
    # Remove links
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    
    # Clean whitespace
    text = " ".join(text.split())
    
    # Truncate to avoid too long TTS segments
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0] + "..."
        
    return text.strip()
