import os
from dotenv import load_dotenv
load_dotenv("backend/.env")
from sqlmodel import Session, select
from database import engine
from models.models import SystemSettings

def fix_settings():
    with Session(engine) as session:
        # Standardize all keys for Plug & Play
        settings_to_set = {
            "llm_provider": "mistral",
            "llm_model": "mistral-small-latest",
            "tts_model": "aura-asteria-en",
            "ai_verbosity": "1",
            "voice_engine": "mistral" # Backward compatibility
        }
        
        for key, value in settings_to_set.items():
            setting = session.exec(select(SystemSettings).where(SystemSettings.key == key)).first()
            if not setting:
                print(f"Creating {key} -> {value}")
                session.add(SystemSettings(key=key, value=value))
            else:
                print(f"Updating {key}: {setting.value} -> {value}")
                setting.value = value
                session.add(setting)
        
        session.commit()
    print("Database settings standardized and set to Mistral.")

if __name__ == "__main__":
    fix_settings()
