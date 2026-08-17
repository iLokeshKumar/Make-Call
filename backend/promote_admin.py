import sys
from sqlmodel import Session, select
from database import engine, User

def promote_user(username: str):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user:
            print(f"Error: User '{username}' not found.")
            return
        
        user.role = "admin"
        session.add(user)
        session.commit()
        print(f"Success: User '{username}' has been promoted to 'admin'.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python promote_admin.py <username>")
    else:
        promote_user(sys.argv[1])
