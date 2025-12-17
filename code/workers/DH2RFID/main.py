# This is a fastAPI worker for handling DH2 RFID operations
# It exposes endpoints to read and write RFID tags using DH2 RFID readers.
# It also exposes a POST endpoint to set the date and time on the board.
# It also has a GET endpoint to get all the entries from the board after a specified timestamp.

# Meant to be run like:
#   uv run fastapi dev --port 8001
# or whatever port you want that's not in use

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import datetime
import random

# The actual library that knows how to talk to the DH2 RFID board
# https://github.com/uhppoted/uhppoted-lib-python
import uhppoted

from dhs_logging import logger

# Our FastAPI app
app = FastAPI()

###############################################################################
# Data Models
###############################################################################

# Model for RFID Entry - this is used to represent an RFID tag entry from the board
# with its tag ID and timestamp that we use to get entries after a certain time.
class RFIDEntry(BaseModel):
    tag_id: str
    timestamp: datetime.datetime


# The list of RFID entris that we are going to return to the caller
rfid_entries: List[RFIDEntry] = []

###############################################################################
# UHPPOTED RFID Board Interaction Functions
###############################################################################

def perform_board_operation(operation: str, tag_id: str = '', converted_tag: str = ''):
    # This function would contain the actual logic to interact with the DH2 RFID board
    # using the uhppoted library. For now, it's just a placeholder.
    logger.info(f"Performing board operation: {operation} on tag_id: {tag_id} with converted_tag: {converted_tag}")

    return True  # Simulate success


###############################################################################
# Healthcheck endpoint
###############################################################################

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": os.getenv("SERVICE_NAME", "DH_SERVICE")}


###############################################################################
# Endpoint to set date and time on the DH2 RFID board
###############################################################################

@app.post("/set_datetime")
async def set_datetime():
    logger.info(f"Setting date and time on the board to: {datetime.datetime.now()}")
    current_time = datetime.datetime.now()
    
    # Here we would have code to actually set the date and time on the board
    # For now, we just simulate success
    
    return {"status": "success", "message": f"Date and time set to {current_time}"}


@app.get("/get_entries_after/{timestamp}", response_model=List[RFIDEntry])
async def get_entries_after(timestamp: str):
    logger.info(f"Fetching entries after timestamp: {timestamp}")
    try:
        ts = datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid timestamp format. Use ISO format."
        )
        
    # Here is where we would fetch entries from the actual board
    # For now, we filter our simulated in-memory entries
    
    filtered_entries = [entry for entry in rfid_entries if entry.timestamp > ts]
    return filtered_entries


# Endpoint to add RFID entries
@app.post("/add_entry")
async def add_entry(entry: dict):
    # Our dictionary looks like:
    # {"member_id": "12345", "first_name": "John", "last_name": "Doe", "tag": "ABCDEF123456", "converted_tag": "123456ABCDEF"}
    logger.info(f"ADDING tag {entry.get('tag', 'unknown')} for member {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})")
    tag = entry.get("tag")
    converted_tag = entry.get("converted_tag")
    
    # Okay, now hand it off to the board interaction function to do the actual addition
    success = perform_board_operation("add", tag_id=tag, converted_tag=converted_tag)
    
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to add tag {tag} to the board")
    
    return {"status": "success", 
            "message": f"Tag {tag} added successfully for {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})"}

# Endpoint to remove a tag from the RFID board
@app.post("/remove_entry")
async def remove_entry(entry: dict):
    # Our dictionary looks like:
    # {"member_id": "12345", "first_name": "John", "last_name": "Doe", "tag": "ABCDEF123456", "converted_tag": "123456ABCDEF"}
    logger.info(f"REMOVING tag {entry.get('tag', 'unknown')} for member {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})")
    tag = entry.get("tag")
    converted_tag = entry.get("converted_tag")
    
    # Okay, now hand it off to the board interaction function to do the actual removal
    success = perform_board_operation("remove", tag_id=tag, converted_tag=converted_tag)

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to remove tag {tag} from the board")
    
    return {
        "status": "success",
        "message": f"Tag {tag} removed successfully for {entry.get('first_name', 'unknown')} {entry.get('last_name', 'unknown')} (id {entry.get('member_id', 'unknown')})",
    }
