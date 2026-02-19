import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select
from database import get_session, User
from pydantic import BaseModel
import os
import pyotp
import qrcode
import base64
from io import BytesIO
from optparse import Option
from typing import Optional, List
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Fix for bcrypt compatibility with passlib 1.7.4+
import bcrypt

# CONFIGURATION
SECRET_KEY = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

def verify_password(plain_password: str, hashed_password: str):
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str):
    # bcrypt limit is 72 bytes. We truncate to ensure stability, though passwords are usually shorter.
    pwd_bytes = password.encode('utf-8')[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    print(f"DEBUG: Validating Token - Secret: {SECRET_KEY[-4:]}, Algo: {ALGORITHM}")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            print("DEBUG: Token validation failed - No 'sub' found")
            raise credentials_exception
        token_data = TokenData(username=username)
    except jwt.ExpiredSignatureError:
        print("DEBUG: Token validation failed - Expired Signature")
        raise credentials_exception
    except jwt.InvalidTokenError as e:
        print(f"DEBUG: Token validation failed - Invalid Token: {str(e)}")
        raise credentials_exception
    except jwt.PyJWTError as e:
        print(f"DEBUG: Token validation failed - PyJWT Error: {str(e)}")
        raise credentials_exception
        
    user = session.exec(select(User).where(User.username == token_data.username)).first()
    if user is None:
        print(f"DEBUG: Token validation failed - User '{token_data.username}' not found in DB")
        raise credentials_exception
    print(f"DEBUG: Token validated for user: {user.username} (Role: {user.role})")
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        print(f"DEBUG: Active check failed for user: {current_user.username}")
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

class RoleChecker:
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_active_user)):
        if user.role not in self.allowed_roles:
            print(f"DEBUG: Role check failed. User role: {user.role}, Allowed: {self.allowed_roles}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for your role"
            )
        return user

# MFA Helpers
def generate_mfa_secret():
    return pyotp.random_base32()

def verify_mfa_token(secret: str, token: str):
    totp = pyotp.TOTP(secret)
    return totp.verify(token)

def get_mfa_provisioning_uri(username: str, secret: str):
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name="Rio-CRM")

def generate_mfa_qr_base64(uri: str):
    img = qrcode.make(uri)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()
