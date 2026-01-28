import os
import time
import uuid
import json
from typing import List
import datetime
import random

from fastapi import FastAPI, HTTPException

from config import config
from dhs_logging import logger

# Our FastAPI app
app = FastAPI()

#
# Okay, why are we not just talking to the board directly here?
# Because this worker is designed to be run in a containerized environment
# where direct hardware access may not be possible. Instead, we will send 
# a message to another service (DHRFIDReader) that has access to the hardware.
#
# How do we do this? This service will write messages to a queue directory
# that the DHRFIDReader service monitors. When it sees a new message, it will
# process it and write a response to a response directory that this service
# will monitor for a response. The queue and response directories are shared
# volumes between the two services (check the docker-compose.yaml file).
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

def perform_board_operation(operation, tag_id=None, converted_tag=None, timeout=10):
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
    return {"status": "healthy", "service": os.getenv("SERVICE_NAME", "DH_DH2RFID_Worker")}


###############################################################################
# Endpoint to set date and time on the DH2 RFID board
###############################################################################

@app.get("/get_datetime")
async def get_datetime():    
    success, data = perform_board_operation("get_datetime")
    logger.info(f"Got date and time from board: {data}")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to get date and time from the board")
    if data is None:
        raise HTTPException(status_code=500, detail="Invalid response from the board")
    
    return {"status": "success", "current_time": data["data"]["current_time"]}

@app.post("/set_datetime")
async def set_datetime():
    current_time = datetime.datetime.now()
    logger.info(f"Setting date and time on the board to: {current_time}")
    success, data = perform_board_operation("set_datetime", tag_id=current_time.isoformat())
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set date and time on the board")
        
    return {"status": "success", "message": f"Date and time set to {current_time}"}


###############################################################################
# Endpoint to add or remove tags from the RFID board
###############################################################################

@app.post("/add_entry")
async def add_entry(entry: dict):
    # Our dictionary looks like:
    # {"member_id": "12345", "first_name": "John", "last_name": "Doe", "tag": "0001460114", "converted_tag": 1234567}
    logger.info(f"ADDING tag {entry.get('tag', 'unknown')} for member {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})")
    tag = entry.get("tag")
    converted_tag = entry.get("converted_tag")
    
    # Okay, now hand it off to the board interaction function to do the actual addition
    success, data = perform_board_operation("add", tag_id=tag, converted_tag=converted_tag)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to add tag {tag} to the board")
    
    return {"status": "success", 
            "message": f"Tag {tag} added successfully for {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})"}

# Endpoint to remove a tag from the RFID board
@app.post("/remove_entry")
async def remove_entry(entry: dict):
    # Our dictionary looks like:
    # {"member_id": "12345", "first_name": "John", "last_name": "Doe", "tag": "0001460114", "converted_tag": 1234567}
    logger.info(f"REMOVING tag {entry.get('tag', 'unknown')} for member {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})")
    tag = entry.get("tag")
    converted_tag = entry.get("converted_tag")
    
    # Okay, now hand it off to the board interaction function to do the actual removal
    success, data = perform_board_operation("remove", tag_id=tag, converted_tag=converted_tag)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to remove tag {tag} from the board")
    
    return {
        "status": "success",
        "message": f"Tag {tag} removed successfully for {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})",
    }
