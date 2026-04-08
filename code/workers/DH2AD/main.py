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

###############################################################################
# Dev Mode Configuration
###############################################################################

# When DEV_MODE is set, we skip the file queue and controller communication
# and return simulated success responses instead. This lets us run without
# DHADController in the dev environment.
DEV_MODE = os.environ.get("DEV_MODE", "").lower() in ("true", "1", "yes")
if DEV_MODE:
    logger.info("DEV_MODE is enabled — controller communication will be simulated")

#
# Okay, we do *not* talk to Active Directory or B2C directly here.
# Because this worker is designed to be run in a containerized environment
# where direct access to AD or B2C may not be possible. Instead, we will send 
# a message to another service (DHADController) that has access to AD and B2C.
# (Okay yes we could do B2C stuff here, but we're not gonna do that so we
# can keep all the AD and B2C logic in one place and not have to worry about
# authentication in multiple places and all that fun stuff)
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

def perform_ad_operation(operation, payload=None, timeout=10):
    if payload is None:
        payload = {}
    payload["operation"] = operation

    # In dev mode, skip the file queue and return a simulated success
    # so we don't need the DHADController service running
    if DEV_MODE:
        logger.info(f"DEV_MODE active — skipping controller, returning simulated success for '{operation}'")
        mock_payload = dict(payload)
        mock_payload["current_time"] = datetime.datetime.now().isoformat()
        return True, {
            "result": "success",
            "status": "success",
            "data": {
                "status": "success",
                "data": mock_payload
            }
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


################################################################################
# Testing endpoint to get date and time from Active Directory -
# We can use this to verify the connection to Active Directory is working 
# properly, since we will be getting the date and time directly from AD and not 
# from the container's system clock
################################################################################

@app.get("/get_datetime")
async def get_datetime():    
    success, data = perform_ad_operation("get_datetime")
    logger.info(f"Got date and time from active directory: {data}")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to get date and time from active directory")
    if data is None:
        raise HTTPException(status_code=500, detail="Invalid response from active directory")
    
    return {"status": "success", "current_time": data["data"]["data"]["current_time"]}


###############################################################################
# User management endpoints - these will call perform_ad_operation with to 
# create users, enable or disable users, etc.
###############################################################################

# For the sync_account_info endpoint, we expect a payload like this:
# {
#   "username": "zesty",
#   "dh_id": 3033,
#   "email_address": "zesty@zesty.com",
#   "nickname": "Zesty",
#   "last_name": "Zest",
#   "first_name": "Zesty",
# }
# This endpoint is for syncing account info like name, email address, birthday, etc.
# DHIdentity will call this endpoint when it gets a request to change a user's 
# identity info, and we will then send a message to DHADController to update 
# the user's info in AD and B2C. If the user doesn't exist in AD or B2C, we can 
# create them, and if they do exist we can update their info.
@app.post("/v1/sync_account_info")
async def sync_account_info(request: dict):
    logger.debug(f"Sync account info request received: {request}")
    try:
        username = request.get("username")
        dh_id = request.get("dh_id")
        
        logger.info(f"Syncing account info for AD username {username} and DH ID {dh_id}")
        
        result = perform_ad_operation("sync_account_info", payload=request)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to sync account info with Active Directory")
        success, data = result
        if not success:
            raise HTTPException(status_code=500, detail="Failed to sync account info with Active Directory")
        
        logger.debug(f"Account info synced successfully with Active Directory: {data}")
        
        if data is None:
            raise HTTPException(status_code=500, detail="Invalid response from Active Directory")
        
        logger.debug(f"Returning data from Active Directory: {data['data']}")
        return data["data"]
    except Exception as e:
        logger.error(f"Error syncing account info: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: " + str(e))


# For the create_user endpoint, we expect a payload like this:
# {
#     "username": "jdoe",
#     "first_name": "John",
#     "last_name": "Doe",
#     "email_address": "foo@test.com",
#     "dh_id": "12345"
# }
@app.post("/v1/create_user")
async def create_user(request: dict):
    logger.debug(f"Ooo, gonna create a new user: {request}")
    try:
        username = request.get("username")
        first_name = request.get("first_name")
        last_name = request.get("last_name")
        email_address = request.get("email_address")        
        dh_id = request.get("dh_id")
        
        logger.info(f"Creating user in Active Directory: {username}, {first_name} {last_name}, {email_address} with DH ID {dh_id}")        
        
        result = perform_ad_operation("create_user", payload=request)
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to create user in Active Directory")
        success, data = result
        if not success:
            raise HTTPException(status_code=500, detail="Failed to create user in Active Directory")
        
        logger.debug(f"User created successfully in Active Directory: {data}")
        
        if data is None:
            raise HTTPException(status_code=500, detail="Invalid response from Active Directory")
        
        if data is not None and ("data" not in data or "data" not in data["data"]):
            raise HTTPException(status_code=500, detail="Invalid response from Active Directory")
                
        return data["data"]
        
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: " + str(e))

# This endpoint is for enabling or disabling a user in AD
# For the set_member_enabled endpoint, we expect a payload like this:
# {
#     "username": "jdoe",
#     "enabled": true
# }
@app.post("/v1/set_member_enabled")
async def set_member_enabled(request: dict):
    logger.debug(f"Ooo, gonna set user enabled state: {request}")
    try:
        username = request.get("username")
        enabled_state = request.get("enabled", False)
        
        logger.info(f"Setting member enabled state in Active Directory: {username}, enabled={enabled_state}")        
        
        result = perform_ad_operation("set_user_enabled", 
                                      payload={"username": username, "enabled": enabled_state})
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to set member enabled state in Active Directory")
        success, data = result
        if data is None:
            raise HTTPException(status_code=500, detail="Invalid response from Active Directory")
        if not success:
            logger.error(f"Failed to set member enabled state in Active Directory: {data}")
            raise HTTPException(status_code=500, detail="Failed to set member enabled state in Active Directory")
        
        # We expect the data to be something like this: {"status": "success", "data": {"username": "jdoe", "enabled": true}}
        if data.get("status") != "success":
            logger.error(f"Failed to set member enabled state in Active Directory: {data}")
            raise HTTPException(status_code=500, detail="Failed to set member enabled state in Active Directory")
                
        return data["data"]        
    except Exception as e:
        logger.error(f"Error setting member enabled state: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: " + str(e))

@app.post("/v1/update_user_ssh_keys")
async def update_user_ssh_keys(request: dict):
    logger.debug(f"Ooo, gonna set user ssh keys: {request}")
    try:
        username = request.get("username")
        ssh_keys = request.get("ssh_keys", [])
        logger.info(f"Setting member ssh keys: {username}, ssh_keys={ssh_keys}")
        result = perform_ad_operation("update_user_ssh_keys",
                                      payload={"username", username, "ssh_keys",
                                               ssh_keys})
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to update member SSH keys in AD")
        success, data = result
        if data is None:
            raise HTTPException(status_code=500, detail="Invalid response from Active Directory")
        if not success:
            logger.error(f"Failed to set member ssh keys: {data}")
            raise HTTPException(status_code=500, detail="Failed to update SSH keys in AD")
        if data.get("status") != "success":
            logger.error(f"Failed to set member ssh keys: {data}")
            raise HTTPException(status_code=500, detail="Failed to update SSH keys in AD")
        return data["data"]
    except Exception as e:
        logger.error(f"Failed to set member ssh keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to update SSH keys in AD")

###############################################################################
# Authorization management endpoints - these will call perform_ad_operation to add or
# remove users from groups in Active Directory, etc.
###############################################################################


# This endpoint will take a payload like this:
# {
#     "username": "jdoe",
#     "status": "add", # or "remove"
#     "authorizations": ["Wood Mini Lathe", "Band Saw"]  # This is a list of group names that the user should be in
# }
@app.post("/v1/sync_authorizations")
async def configure_authorizations(request: dict):
    logger.info(f"Configure authorizations request received: {request}")

    try:
        username = request.get("username")
        status = request.get("status", "add")
        authorizations = request.get("authorizations", [])
        logger.info(f"Configuring authorizations for user {username} with status {status} and authorizations {authorizations}")
        
        for auth in authorizations:
            # We set the full DN in the DHADController program since it has the logic to determine the correct base DN, 
            # so we just pass the auth name here and let DHADController figure it out 
            group_dn = auth 
            
            if status == "add":
                logger.info(f"Adding user {username} to group {group_dn}")
                result = perform_ad_operation("add_user_to_group", payload={"username": username, "group_dn": group_dn})
            elif status == "remove":
                logger.info(f"Removing user {username} from group {group_dn}")
                result = perform_ad_operation("remove_user_from_group", payload={"username": username, "group_dn": group_dn})
            else:
                raise HTTPException(status_code=400, detail="Invalid status value. Must be 'add' or 'remove'.")
            
            if result is None:
                raise HTTPException(status_code=500, detail=f"Failed to update authorization for {auth}")
            success, data = result
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to update authorization for {auth}")

        logger.info(f"Authorizations configured successfully for user {username}")
        return {
                "status": "success",
                "data": {
                    "username": username,
                    "action": "added to" if status == "add" else "removed from",
                    "authorizations": authorizations
                }
            }        
    except Exception as e:
        logger.error(f"Error configuring authorizations: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: " + str(e))
