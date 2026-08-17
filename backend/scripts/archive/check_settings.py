import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check():
    with SessionLocal() as session:
        result = session.execute(text("SELECT key, value FROM systemsettings"))
        settings = {row[0]: row[1] for row in result}
        print(f"Current Settings: {settings}")

if __name__ == "__main__":
    check()
