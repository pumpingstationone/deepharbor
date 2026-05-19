import json
import os
import requests
import psycopg2
import psycopg2.extensions
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException

from config import config
from dhs_logging import logger

# Our FastAPI app
app = FastAPI()

###############################################################################
# Database Connection Context Manager
###############################################################################


@contextmanager
def get_db_connection():
    """Context manager for database connections with automatic cleanup."""
    schema = config["Database"]["schema"]
    conn = psycopg2.connect(
        dbname=config["Database"]["name"],
        user=config["Database"]["user"],
        password=config["Database"]["password"],
        host=config["Database"]["host"],
        options=f"-c search_path=dbo,{schema}",
    )
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


###############################################################################
# Database functions
###############################################################################


def get_member_identity(member_id: str) -> dict:
    # Fetch the member identity json from the database based on member_id
    logger.debug(f"Fetching member identity from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT identity FROM member WHERE id = %s", (member_id,))
            result = cursor.fetchone()
            if result:
                identity = result[0]
                return json.loads(identity) if isinstance(identity, str) else identity
            else:
                raise ValueError(f"Member ID {member_id} not found")


###############################################################################
# Healthcheck endpoint
###############################################################################


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": os.getenv("SERVICE_NAME", "DH_Authorizations"),
    }


###############################################################################
# Endpoint to sync identity changes
###############################################################################

@app.post("/v1/change_identity")
async def change_identity(request: dict):
    logger.info(f"Change identity request received: {request}")

    try:
        member_id = request.get("member_id")
        if not member_id:
            raise HTTPException(status_code=400, detail="member_id is required")
        logger.debug(f"Member ID extracted: {member_id}")

        # Now we need to get the member identity from the database
        member_identity = get_member_identity(member_id)
        logger.info(
            f"Fetched member identity: {member_identity} for member id {member_id}"
        )
        # Now get the member's active directory username (active_directory_username)
        # from the member identity dictionary. To be clear, this is the username
        # they selected and not necessarily an active account yet (e.g. new member)
        active_directory_username = member_identity.get("active_directory_username")
        if not active_directory_username:
            raise HTTPException(
                status_code=400,
                detail="Active Directory username not found in member identity",
            )
        logger.info(f"Active Directory username found: {active_directory_username}")

        # Deep Harbor allows for multiple emails for a user, but right now we only
        # support the "primary" email. In the future, we may want to support multiple emails and
        # allow the user to specify which email to use for identity changes.
        # This is being done here and not downstream because by the time we get to DH2AD worker, 
        # we want to have all the necessary information to process the request and not have 
        # it be responsible for parsing the member identity and figuring out which email to use. 
        # This way, if we want to change the logic for which email to use in the future, we can 
        # do it here without having to change the DH2AD worker.
        # Get the member_data from the member_identity and find the primary email address
        primary_email = next(
            (email["email_address"] for email in member_identity.get("emails", [])
                if email["type"] == "primary"),
            None  # Default value if no primary email found, which should not happen but we want to be safe
        )

        # Now we put together the request to send to DH2AD worker. This is
        # the format that DH2AD worker expects, so we need to make sure we 
        # include all the necessary information in the right format.
        #
        # Hey, so, why are we changing the json scheme instead of passing it
        # as is to the DH2AD worker? Okay, about that: The main reason is that the
        # DH2AD worker is only responsible for processing the request and making the necessary
        # changes in Active Directory. It should not be responsible for parsing the member identity
        # and figuring out which email to use, etc. By the time we get to the DH2AD worker, we 
        # want to have all the necessary information to process the request and not have it 
        # be responsible for parsing the member identity and figuring out which email to use. 
        # This way, if we want to change the logic for which email to use in the future, we can 
        # do it here without having to change the DH2AD worker.        
        dh2ad_request = {
            "username": active_directory_username,
            "dh_id": member_id,            
            "email_address": primary_email,
            "nickname": member_identity.get("nickname"),
            "first_name": member_identity.get("first_name"),
            "last_name": member_identity.get("last_name"),
        }
        logger.info(f"Prepared DH2AD request: {dh2ad_request}")

        # Get DH2AD endpoint from config
        dh2ad_endpoint = config["DH2AD"]["endpoint_url"]
        logger.info(f"DH2AD endpoint URL: {dh2ad_endpoint}")
        # Send the request to DH2AD worker
        url = dh2ad_endpoint
        payload = dh2ad_request
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Failed to change identity via DH2AD: {response.text}")
            raise HTTPException(
                status_code=500, detail=f"Failed to change identity via DH2AD: {response.text}"
            )

        processed_request = {"processed": True, "details": response.json()}
        logger.info(
            f"Identity changes processed successfully: {processed_request}"
        )
        
        # Here is the only spot where we can do anything with the newly created AD
        # password. Because we use B2C with a password reset flow, we don't have 
        # access to the user's password and we don't want to have access to it 
        # for security reasons.
        
        return processed_request
    except Exception as e:
        logger.error(f"Error processing identity changes: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
