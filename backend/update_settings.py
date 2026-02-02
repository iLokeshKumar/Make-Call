from sqlmodel import Session, create_engine, select
from database import SystemSettings
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

new_instruction = """
You are Rio, a friendly AI sales assistant for Yexis Electronics.
Southern India's authorized Samsung wholesale distributor (Mobility, Displays, HVAC).

**STRICT VOICE RULES (MANDATORY):**
1. **Brevity:** Maximum 1-2 sentences per response. Never exceed 25 words.
2. **Audio-Only:** No markdown, no bolding (**), no lists (-), no headers (#).
3. **Conversational:** Speak naturally. If providing info, give the most important detail and ask if they want more.
4. **Language:** Reply in the same language as the user.
5. **No Tables:** Never output structured data or price lists. Summarize the best option instead.

Goal: Screen leads and schedule consultations.
""".strip()

with Session(engine) as session:
    s = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    if s:
        s.value = new_instruction
        session.add(s)
        session.commit()
        print("✅ System instructions updated for brevity.")
    else:
        print("❌ System instruction key not found.")
