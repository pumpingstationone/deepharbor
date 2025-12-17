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


def get_member_identity(member_id: str) -> str:
    # Fetch the member identity json from the database based on member_id
    logger.debug(f"Fetching member identity from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT identity FROM member WHERE id = %s", (member_id,))
            result = cursor.fetchone()
            if result:
                return result[0]
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
# Endpoint to sync authorizations
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
        # from the member identity JSON
        # For simplicity, let's assume member_identity is a dict with the needed info
        active_directory_username = member_identity.get("active_directory_username")
        if not active_directory_username:
            raise HTTPException(
                status_code=400,
                detail="Active Directory username not found in member identity",
            )

        logger.info(f"Active Directory username found: {active_directory_username}")

        # Now we put together the request to send to DH2AD worker
        dh2ad_request = {
            "user_id": active_directory_username,
            "authorizations": request.get("change_data", []),
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
            logger.error(f"Failed to change authorizations via DH2AD: {response.text}")
            raise HTTPException(
                status_code=500, detail=f"Failed to change authorizations via DH2AD: {response.text}"
            )

        # Simulate processing
        processed_request = {"processed": True, "details": request}
        logger.info(
            f"Authorization changes processed successfully: {processed_request}"
        )
        return processed_request
    except Exception as e:
        logger.error(f"Error processing authorization changes: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
