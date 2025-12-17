from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel

from config import config
from models import Client
from db import get_client_by_client_name

from dhs_logging import logger

###############################################################################
# Configuration
###############################################################################

# to get a string like this run:
# openssl rand -hex 32
# and store it in the config.ini file
SECRET_KEY = config["oauth2"]["secret_key"]
ALGORITHM = config["oauth2"]["algorithm"]
ACCESS_TOKEN_EXPIRE_MINUTES = int(config["oauth2"]["access_token_expire_minutes"])

###############################################################################
# Private classes for oauth2
###############################################################################

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    client_name: str | None = None


###############################################################################
# Oauth2 configuration
###############################################################################

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

###############################################################################
# Oauth2 functions
###############################################################################

def verify_password(plain_password, hashed_password):
    logger.debug(f"plain_password: {plain_password}")
    logger.debug(f"hashed_password: {hashed_password}")
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def get_client(client_name: str):
    client = get_client_by_client_name(client_name)
    if client is None:
        return None
    return client


def authenticate_client(client_name: str, password: str):
    client = get_client_by_client_name(client_name)
    if not client:
        return False
    if not verify_password(password, client.hashed_password):
        return False
    return client


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_client(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # logger.debug(f"payload: {payload}")
        client_name: str = payload.get("sub")
        if client_name is None:
            raise credentials_exception
        token_data = TokenData(client_name=client_name)
    except InvalidTokenError:
        raise credentials_exception
    client = get_client(client_name=token_data.client_name)
    if client is None:
        raise credentials_exception
    return client


async def get_current_active_client(
    current_client: Annotated[Client, Depends(get_current_client)],
):
    if current_client.disabled:
        raise HTTPException(status_code=400, detail="Inactive client")
    return current_client
