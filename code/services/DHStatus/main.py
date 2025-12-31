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

# Get member identity from the database, which includes the active directory
# username needed for DH2AD service
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

# Gets the RFID tags associated with the member from the database
# Needed for the DH2RFID service
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
        "service": os.getenv("SERVICE_NAME", "DH_Status"),
    }

###############################################################################
# Service Endpoints Functions
#   These would be used to call other services as needed
###############################################################################

# This is the meta function that will find and call other services as needed
# If other services need to be called, this is where that logic would go
def perform_status_changes(member_id: str, change_type: str):
    # Get the member identity to log who this is about
    
    member_identity = get_member_identity(member_id)
    logger.info(f"Processing status change for member identity: {member_identity}")
    first_name = member_identity.get("first_name", "Unknown")
    last_name = member_identity.get("last_name", "Unknown")

    logger.info(f"Member {first_name} {last_name} (ID {member_id}) status changed to {change_type}")
    
    #
    # Active directory changes via DH2AD
    #
    dh2ad_url = config["DH2AD"]["endpoint_url"]
    dh2ad_payload = {
        "username": member_identity.get("active_directory_username"),
        "enabled": change_type        
    }
    try:
        response = requests.post(dh2ad_url, json=dh2ad_payload)
        response.raise_for_status()
        logger.info(f"DH2AD response: {response.json()}")
    except requests.RequestException as e:
        logger.error(f"Error calling DH2AD service: {str(e)}")
        return False, str(e)

    #
    # RFID tag changes via DH2RFID
    #
    dh2rfid_url = config["DH2RFID"]["base_endpoint_url"]
    if change_type == "active":
        dh2rfid_url += config["DH2RFID"]["add_tags_endpoint"]
    else:
        dh2rfid_url += config["DH2RFID"]["remove_tags_endpoint"]        

    dh2rfid_request = {
            "member_id": member_id,
            "first_name": first_name,
            "last_name": last_name,
            "tag": '',
            "converted_tag": ''
        }
    tags = get_member_tags(member_id)
    for tag_entry in tags:
        # We are only processing ACTIVE tags here, in other words, tags that
        # are currently assigned to the member. If the member is being deactivated,
        # those tags will be removed from the board controller. 
        # If the member is being activated, those tags will be added
        # to the board controller.
        if tag_entry.get("status") == "ACTIVE":
            dh2rfid_request["tag"] = tag_entry.get("tag")
            dh2rfid_request["converted_tag"] = tag_entry.get("converted_tag")
            try:
                response = requests.post(dh2rfid_url, json=dh2rfid_request)
                response.raise_for_status()
                logger.info(f"DH2RFID response for tag {tag_entry.get('tag')}: {response.json()}")
            except requests.RequestException as e:
                logger.error(f"Error calling DH2RFID service for tag {tag_entry.get('tag')}: {str(e)}")
                return False, str(e)
    
        
    # If we reach here, all status changes were successful
    return True, None


###############################################################################
# Endpoint to status changes
###############################################################################

@app.post("/v1/change_status")
def change_status(request: dict):
    logger.debug(f"Received status change request: {request}")
    # Our dict looks like:
    # {'member_id': 1, 'change_type': 'status', 'change_data': {'donor': False, 'balance': 0.0, 'donations': 0.0, 'member_id': '1', 'member_since': '2018-05-12T00:00:00-05:00', 'renewal_date': None, 'membership_level': 'Area Host', 'membership_status': 'active', 'stripe_customer_id': None}}
    
    # Let's get the membership status from change_data
    change_data = request.get("change_data", {})
    membership_status = change_data.get("membership_status")

    changed_status, error_message = perform_status_changes(request.get("member_id"), membership_status)        
    
    if changed_status is True:
        logger.info(f"Successfully processed status change for member id {request.get('member_id')}")
    else:
        logger.error(f"Failed to process status change for member id {request.get('member_id')}: {error_message}")
        raise HTTPException(status_code=500, detail=f"Failed to process status change for member id {request.get('member_id')}: {error_message}")
    
    return {"processed": True}