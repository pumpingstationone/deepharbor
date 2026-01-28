import json
import time
import os
import glob
import uuid
import datetime

import ad
import b2c
from dhs_logging import logger
from config import config

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
PROCESSING_DIR = os.path.join(BASE_DIR, "processing")
if not os.path.exists(PROCESSING_DIR):
    os.makedirs(PROCESSING_DIR)
    
###############################################################################
# Active Directory / B2C Interaction Functions
###############################################################################
def get_datetime():
    try:
        current_time = ad.get_current_datetime()
        logger.info(f"Current AD date and time: {current_time}")
        return {
            "status": "success",
            "data": {
                "current_time": current_time.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error getting date and time from AD: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }

###############################################################################
# Message Queue Interaction Functions
###############################################################################

def handle_message(msg_id, payload):
    operation = payload.get("operation")
    tag_id = payload.get("tag_id")
    converted_tag = payload.get("converted_tag")
    
    if operation in ["add", "remove"]:
        #success = perform_ad_operation(operation, tag_id, converted_tag)
        success = True  # Placeholder for actual operation
        result_data = {
            "original_id": msg_id,
            "operation": operation,
            "tag_id": tag_id,
            "converted_tag": converted_tag,
            "status": "success" if success else "failure"
        }   
    elif operation == "get_datetime":
        result_data = get_datetime()
        result_data["original_id"] = msg_id
    else:
        result_data = {
            "original_id": msg_id,
            "status": "failure",
            "error": f"Unknown operation: {operation}"
        }
    
    return result_data

def process_queue():
    logger.info("DHADController Worker started. Monitoring queue...")
    
    while True:
        # Get list of .json files in queue
        queue_files = glob.glob(os.path.join(QUEUE_DIR, "*.json"))
        
        # Sort by creation time (optional, ensures FIFO)
        queue_files.sort(key=os.path.getmtime)

        if not queue_files:
            time.sleep(0.1)
            continue

        # Pick the oldest file
        current_file = queue_files[0]
        filename = os.path.basename(current_file)
        msg_id = filename.replace(".json", "")
        
        # 1. Get the message
        # Move it to a 'processing' folder to handle it
        processing_path = os.path.join(PROCESSING_DIR, filename)
        
        try:
            os.rename(current_file, processing_path)
        except FileNotFoundError:
            # Hmm, why is it not here? Maybe another process took it?
            continue

        try:
            # 2. Read and Process
            with open(processing_path, 'r') as f:
                data = json.load(f)
            
            logger.info(f"Processing {msg_id}: {data['payload']}")
            
            # Now handle the message
            message_data = handle_message(msg_id, data['payload']) 
            logger.debug(f"Result for {msg_id}: {message_data}")
            
            result_data = {
                "original_id": msg_id,
                "result": f"Processed '{data['payload']}'",
                "status": "success",
                "data": message_data
            }

            # 3. Write Response Atomically
            tmp_resp = os.path.join(BASE_DIR, f".tmp_resp_{msg_id}")
            final_resp = os.path.join(RESPONSE_DIR, filename)

            with open(tmp_resp, 'w') as f:
                json.dump(result_data, f)
                f.flush()
                os.fsync(f.fileno())
            # Rename is an atomic operation
            os.rename(tmp_resp, final_resp)
        except Exception as e:
            logger.error(f"Error processing {msg_id}: {e}")
        finally:
            # 4. Cleanup
            if os.path.exists(processing_path):
                os.remove(processing_path)
                
def main():
    # Start processing the queue  
    process_queue()

if __name__ == "__main__":
    main()