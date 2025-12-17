# Our services for Deep Harbor

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends

# Our fastapi app
from fastapiapp import app

# Our oauth2 services
import auth

# Our v1 services
import v1

from dhs_logging import logger

###############################################################################
# Healthcheck endpoint
###############################################################################


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": os.getenv("SERVICE_NAME", "DH_SERVICE")}


###############################################################################
# Our endpoints for oauth2
###############################################################################


# This is the token endpoint for oauth2
@app.post("/token")
async def login_for_access_token(
    form_data: Annotated[auth.OAuth2PasswordRequestForm, auth.Depends()],
) -> auth.Token:
    logger.debug("Getting a token...")
    client = auth.authenticate_client(form_data.username, form_data.password)
    if not client:
        raise auth.HTTPException(
            status_code=auth.status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect client name or client secret",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": client.client_name}, expires_delta=access_token_expires
    )
    return auth.Token(access_token=access_token, token_type="bearer")


# This endpoint is to reauthenticate and get a new token
@app.post("/reauthenticate")
async def reauthenticate(
    current_client: auth.Client = Depends(auth.get_current_active_client),
) -> auth.Token:
    logger.debug("Reauthenticating client %s", current_client.client_name)
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": current_client.client_name}, expires_delta=access_token_expires
    )
    return auth.Token(access_token=access_token, token_type="bearer")

###############################################################################
# Endpoints for member passwords
###############################################################################

# Set the password for a member
@app.post("/set_member_password")
async def set_member_password(
    member_id: str,
    new_password: str,
    current_client: auth.Client = Depends(auth.get_current_active_client),
):
    logger.debug(
        "Client %s is setting password for member %s",
        current_client.client_name,
        member_id,
    )
    # Here you would implement the logic to set the member's password
    # For now, we just log and return success
    logger.info("Password for member %s has been set.", member_id)
    return {"status": "success", "member_id": member_id}

# Change the password for a member
@app.post("/change_member_password")
async def change_member_password(
    member_id: str,
    old_password: str,
    new_password: str,
    current_client: auth.Client = Depends(auth.get_current_active_client),
):
    logger.debug(
        "Client %s is changing password for member %s",
        current_client.client_name,
        member_id,
    )
    # Here you would implement the logic to change the member's password
    # For now, we just log and return success
    logger.info("Password for member %s has been changed.", member_id)
    return {"status": "success", "member_id": member_id}


###############################################################################
# HEY! All other endpoints are in the py file that matches their version number
# (for example, v1.py for version 1 endpoints)
###############################################################################
