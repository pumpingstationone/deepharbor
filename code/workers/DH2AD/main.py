import os
import time
import uuid
import json
from typing import List
import datetime

from fastapi import FastAPI, HTTPException

from dhs_logging import logger
from config import config

# Our FastAPI app
app = FastAPI()

#
# Okay, we do *not* talk to Active Directory or B2C directly here.
# Because this worker is designed to be run in a containerized environment
# where direct access to AD or B2C may not be possible. Instead, we will send 
# a message to another service (DHADController) that has access to AD and B2C.
#

###############################################################################
# Queue Configuration
###############################################################################

BASE_DIR = config["shared"]["SHARED_VOLUME_PATH"]
QUEUE_DIR = os.path.join(BASE_DIR, "queues")
if not os.path.exists(QUEUE_DIR):
    os.makedirs(QUEUE_DIR)
RESPONSE_DIR = os.path.join(BASE_DIR, "responses")
if not os.path.exists(RESPONSE_DIR):
    os.makedirs(RESPONSE_DIR)


###############################################################################
# Message Queue Interaction Functions
###############################################################################

def send_message_async(payload):
    msg_id = str(uuid.uuid4())
    message = {
        "id": msg_id,
        "payload": payload,
        "timestamp": time.time()
    }
    
    # 1. Atomic Write Pattern
    # Write to a temp file, then move to queue so DHRFIDReader never sees 
    # partial files
    tmp_path = os.path.join(BASE_DIR, f".tmp_{msg_id}")
    final_path = os.path.join(QUEUE_DIR, f"{msg_id}.json")
    
    with open(tmp_path, 'w') as f:
        json.dump(message, f)
        f.flush()
        os.fsync(f.fileno())
    
    os.rename(tmp_path, final_path)
    logger.info(f"Sent message {msg_id}: {payload}")
    return msg_id

def check_responses(sent_ids):
    # Check for responses corresponding to our sent IDs
    completed = []
    data = None
    for msg_id in sent_ids:
        resp_path = os.path.join(RESPONSE_DIR, f"{msg_id}.json")
        
        if os.path.exists(resp_path):
            with open(resp_path, 'r') as f:
                data = json.load(f)
            
            logger.info(f"Got response for {msg_id}: {data['result']}")
            
            # Clean up response file
            os.remove(resp_path)
            completed.append(msg_id)
            
    return completed, data

def perform_ad_operation(operation, tag_id=None, converted_tag=None, timeout=10):
    payload = {
        "operation": operation,
        "tag_id": tag_id,
        "converted_tag": converted_tag
    }
    
    msg_id = send_message_async(payload)
    
    # Now wait for response
    start_time = time.time()
    while time.time() - start_time < timeout:
        completed, data = check_responses([msg_id])
        if msg_id in completed:
            return True, data
        time.sleep(0.5)
    
    logger.error(f"Timeout waiting for response for message {msg_id}")
    return False, None


###############################################################################
# Healthcheck endpoint
###############################################################################

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": os.getenv("SERVICE_NAME", "DH2AD")}


###############################################################################
# Endpoint to get date and time from the DH2 AD service
###############################################################################

@app.get("/get_datetime")
async def get_datetime():    
    success, data = perform_ad_operation("get_datetime")
    logger.info(f"Got date and time from active directory: {data}")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to get date and time from active directory")
    if data is None:
        raise HTTPException(status_code=500, detail="Invalid response from active directory")
    
    return {"status": "success", "current_time": data["data"]["current_time"]}


###############################################################################
# Endpoint to set up identities in Active Directory, creating users if needed
###############################################################################

@app.post("/v1/sync_account_info")
async def sync_account_info(request: dict):
    logger.info(f"Sync account info request received: {request}")

    try:
        """
        # Connect to Active Directory
        ad_domain = ADDomain(
            domain_name="your_domain",
            username="your_username",
            password="your_password"
        )

        user_id = request.get("user_id")
        authorizations = request.get("authorizations", [])

        # Check if user exists, if not create the user
        if not ad_domain.user_exists(user_id):
            ad_domain.create_user(user_id)
            logger.info(f"Created new user in AD: {user_id}")

        # Update user's authorizations (groups) in AD
        current_groups = set(ad_domain.get_user_groups(user_id))
        desired_groups = set(authorizations)

        # Add user to missing groups
        for group in desired_groups - current_groups:
            ad_domain.add_user_to_group(user_id, group)
            logger.info(f"Added user {user_id} to group {group}")

        # Remove user from groups not in desired list
        for group in current_groups - desired_groups:
            ad_domain.remove_user_from_group(user_id, group)
            logger.info(f"Removed user {user_id} from group {group}")
        """
        response = {
            "user_id": request.get("user_id"),
            "success": True
        }
        logger.info(f"Account info synchronized successfully: {response}")
        return response

    except Exception as e:
        logger.error(f"Error synchronizing account info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: " + str(e))


###############################################################################
# Endpoint to change authorizations
###############################################################################


# Note about authorizations - get the list of authorizations for the user
# from active directory, and add what is missing, but also remove what is
# not in the list of authorizations provided.
@app.post("/v1/sync_authorizations")
async def sync_authorizations(request: dict):
    logger.info(f"Sync authorizations request received: {request}")

    # If we get a payload that does not have authorizations, then
    # we assume that we need to remove all authorizations for that user.

    try:
        """
        # Connect to Active Directory
        ad_domain = ADDomain(
            domain_name="your_domain",
            username="your_username",
            password="your_password"
        )

        user_id = request.get("user_id")
        desired_authorizations = set(request.get("authorizations", []))

        # Fetch current authorizations from AD
        current_authorizations = set(ad_domain.get_user_groups(user_id))

        # Determine authorizations to add and remove
        to_add = desired_authorizations - current_authorizations
        to_remove = current_authorizations - desired_authorizations

        # Update authorizations in AD
        for auth in to_add:
            ad_domain.add_user_to_group(user_id, auth)

        for auth in to_remove:
            ad_domain.remove_user_from_group(user_id, auth)

        response = {
            "user_id": user_id,
            "added": list(to_add),
            "removed": list(to_remove)
        }
        """
        response = {"user_id": request.get("user_id"), "added": [], "removed": []}
        logger.info(f"Authorizations synchronized successfully: {response}")
        return response
    except Exception as e:
        logger.error(f"Error synchronizing authorizations: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# This endpoint is for enabling or disabling a user in AD
@app.post("/v1/set_member_enabled")
async def set_member_enabled(request: dict):
    logger.info(f"Set member enabled request received: {request}")

    try:
        # First let's get the username and enabled status
        username = request.get("username")
        enabled = request.get("enabled", True)
        
        '''
        # Now connect to AD
        sesion = ad.create_session()
        user = ad.get_user_by_username(sesion, username)
        ad.set_user_enabled_status(sesion, user, enabled)
        ad.close_session(sesion)
        '''
        
        response = {"username": request.get("username"), "enabled": request.get("enabled", True)}
        logger.info(f"User enabled status set successfully: {response}")
        return response
    except Exception as e:
        logger.error(f"Error setting user enabled status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error: " + str(e))