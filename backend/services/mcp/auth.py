import os
from fastapi import HTTPException, status
import jwt

RIO_SECRET = os.getenv('RIO_SECRET') or os.getenv('RIO_API_KEY')
RIO_JWT_SECRET = os.getenv('RIO_JWT_SECRET')
RIO_JWT_ALGORITHM = os.getenv('RIO_JWT_ALGORITHM', 'HS256')


def verify_api_call(x_rio_secret: str, authorization: str):
    # Shared secret path
    if RIO_SECRET and x_rio_secret and x_rio_secret == RIO_SECRET:
        return {'method': 'secret'}

    # JWT path
    if authorization:
        token = authorization.split()[1] if authorization.lower().startswith('bearer ') else authorization
        if not RIO_JWT_SECRET:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT secret not configured')
        try:
            payload = jwt.decode(token, RIO_JWT_SECRET, algorithms=[RIO_JWT_ALGORITHM])
            return {'method': 'jwt', 'payload': payload}
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT expired')
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid JWT token')

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing authentication')
