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

# We need to know whether this member is active or not, as this will determine
# whether we add or remove access to the DH2RFID system
def get_member_status(member_id: str) -> str:
    # Fetch the member status from the database based on member_id
    logger.debug(f"Fetching member status from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # This is a bit messy, but we need to extract the membership_status from the 
            # JSONB field in the database.
            status_sql = f"""
                SELECT  trim(both '"' FROM (SELECT status->'membership_status' 
                FROM    member 
                WHERE   id = {member_id})::TEXT) membership_status;
            """
            cursor.execute(status_sql)
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                raise ValueError(f"Member ID {member_id} not found")

def get_member_tags(member_id: str) -> list:
    # Fetch the RFID tags associated with the member from the database
    logger.debug(f"Fetching RFID tags from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Calls the stored procedure to get all tags for the member
            tag_sql = f"""
                select tag, wiegand_tag_num, status from get_all_tags_for_member({member_id});
            """
            cursor.execute(tag_sql)
            results = cursor.fetchall()
            tags = []
            for row in results:
                tags.append({"tag": row[0], "converted_tag": row[1], "status": row[2]})
            return tags

###############################################################################
# Healthcheck endpoint
###############################################################################


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": os.getenv("SERVICE_NAME", "DH_Access"),
    }


###############################################################################
# Endpoint to sync authorizations
###############################################################################


@app.post("/v1/change_access")
async def change_access(request: dict):
    logger.info(f"Change access request received: {request}")

    try:
        # Okay, first we need to get the member ID from the request
        member_id = request.get("member_id")
        if not member_id:
            raise HTTPException(status_code=400, detail="member id is required")
        logger.debug(f"We got Member id: {member_id}")

        # Now we need to get the member identity from the database
        member_identity = get_member_identity(member_id)
        logger.info(
            f"Fetched member identity: {member_identity} for member id {member_id}"
        )
        # Get the name of the member for logging purposes
        first_name = member_identity.get("first_name", "Unknown")
        last_name = member_identity.get("last_name", "Unknown")
        logger.info(f"Processing access change for member: {first_name} {last_name}")
        
        # Now we need to get the status of the member
        member_status = get_member_status(member_id)
        logger.info(
            f"Fetched member status: {member_status} for {first_name} {last_name} (id {member_id})"
        )
        # The only status that allows access is "active". Everything else means we
        # need to remove access.
        access_operation = "add" if member_status.lower() == "active" else "remove"
        logger.info(f"We're going to be performing a {access_operation} operation for member id {first_name} {last_name} (member id: {member_id})")

        # Now we need to get the RFID tags associated with this member. This will
        # come back as a list of tags with their status (active/inactive).
        tags = get_member_tags(member_id)
        logger.info(f"Fetched {len(tags)} tags for {first_name} {last_name} (id {member_id}) : {tags}")
        if not tags:
            # No tags found, nothing to do, but this is not fatal - just log it
            logger.warning(f"No RFID tags found for member {first_name} {last_name} (id {member_id})")
        else:        
            # Okay, cool, if we're here that means we have tags to process. What we set the
            # tags to depend on whether we're adding or removing access. Tags that are
            # marked as "INACTIVE" should always be sent to the "remove" endpoint, while the
            # "ACTIVE" tags should be sent to the "add" endpoint _IF THE MEMBER STATUS IS ACTIVE_,
            # otherwise they should be sent to the "remove" endpoint.
            
            # Get our endpoints ready
            dh2rfid_endpoint = config["DH2RFID"]["base_endpoint_url"]
            logger.info(f"DH2RFID endpoint URL: {dh2rfid_endpoint}")
            dh2rfid_add_endpoint = dh2rfid_endpoint + config["DH2RFID"]["add_tags_endpoint"]
            dh2rfid_remove_endpoint = dh2rfid_endpoint + config["DH2RFID"]["remove_tags_endpoint"]
            logger.info(f"DH2RFID add tags endpoint URL: {dh2rfid_add_endpoint}")
            logger.info(f"DH2RFID remove tags endpoint URL: {dh2rfid_remove_endpoint}")
            
            # Now we need to build the request to send to the DH2RFID worker.
            # The worker doesn't care about member IDs or identities, just the tags,
            # but we're going to include the member id for logging purposes.
            dh2rfid_request = {
                "member_id": member_id,
                "first_name": first_name,
                "last_name": last_name,
                "tag": '',
                "converted_tag": ''
            }
            
            for tag_entry in tags: 
                tag = tag_entry.get("tag")
                converted_tag = tag_entry.get("converted_tag")
                tag_status = tag_entry.get("status")
                if access_operation == "add" and tag_status == "ACTIVE":
                    # We need to add this tag
                    dh2rfid_request["tag"] = tag
                    dh2rfid_request["converted_tag"] = converted_tag
                    logger.info(f"Adding tag {tag} for member id {member_id}")
                    # Send the request to DH2RFID worker
                    url = dh2rfid_add_endpoint
                    logger.debug(f"Add tag URL: {url}")
                    payload = dh2rfid_request
                    response = requests.post(url, json=payload)
                    if response.status_code != 200:
                        logger.error(f"Failed to add tag via DH2RFID: {response.text}")
                        raise HTTPException(
                            status_code=500, detail=f"Failed to add tag via DH2RFID: {response.text}"
                        )
                else:
                    # We need to remove this tag
                    dh2rfid_request["tag"] = tag
                    dh2rfid_request["converted_tag"] = converted_tag
                    logger.info(f"Removing tag {tag} for member id {member_id}")
                    # Send the request to DH2RFID worker
                    url = dh2rfid_remove_endpoint
                    logger.debug(f"Remove tag URL: {url}")
                    payload = dh2rfid_request                
                    response = requests.post(url, json=payload)
                    if response.status_code != 200:
                        logger.error(f"Failed to remove tag via DH2RFID: {response.text}")
                        raise HTTPException(
                            status_code=500, detail=f"Failed to remove tag via DH2RFID: {response.text}"
                        )
            
        # Cool, if we got here then everything worked
        # Report success back to the caller        
        processed_request = {"processed": True, "details": request}
        logger.info(
            f"Authorization changes processed successfully: {processed_request}"
        )
        return processed_request
    except Exception as e:
        logger.error(f"Error processing authorization changes: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")