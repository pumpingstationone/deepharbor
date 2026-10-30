import os
from uaaccess import UnifiAccessAPI
from config import config
import time
from dhs_logging import logger
import json
import glob

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

UA_HOSTNAME = config["unifi_api"]["HOSTNAME"]
UA_TOKEN = config["unifi_api"]["API_TOKEN"]
READER_ID = config["unifi_api"]["ENROLLMENT_READER_ID"]
ACCESS_GROUP = config["unifi_api"]["ACCESS_GROUP_ID"]

# We can only have one enrollment session open at once
# Are we currently in a session / what is the session ID?
ENROLLMENT_SESSION = ""

def handle_message(msg_id, payload):
    global ENROLLMENT_SESSION

    operation = payload.get("operation")
    uaapi = UnifiAccessAPI(UA_HOSTNAME, UA_TOKEN)

    result_data = {}

    # What do we wanna do?
    if operation == "create_user":
        pass

    elif operation == "begin_enrollment":
        if (not ENROLLMENT_SESSION):
            # Do the thing
            ENROLLMENT_SESSION = uaapi.begin_enroll_session(READER_ID)
            result_data = {
                "original_id": msg_id,
                "status": "success",
                "session_id": ENROLLMENT_SESSION
            }
        else:
            result_data = {
                "original_id": msg_id,
                "status": "failure",
                "error": f"Enrollment already claimed by session {ENROLLMENT_SESSION}"
            }

    elif operation == "check_enrollment":
        if (ENROLLMENT_SESSION):
            try:
                id, token_id = uaapi.check_enroll_session(ENROLLMENT_SESSION)
                if (id is not None and token_id is not None):
                    # We have a token!
                    result_data = {
                        "original_id": msg_id,
                        "status": "success",
                        "enrollment_stage": "success",
                        "nfc_id": id,
                        "unifi_token_id": token_id
                    }

                    # Clear out the session so we can have another enrollment
                    ENROLLMENT_SESSION = None
                else:
                    # Enrollment hasn't succeeded yet
                    result_data = {
                        "original_id": msg_id,
                        "status": "pending",
                        "enrollment_stage": "pending_tap"
                    }
            except:
                result_data = {
                    "original_id": msg_id,
                    "status": "failure",
                    "error": f"Exception in checking the enrollment session",
                }

                # There was an error, so zero the session and try again
                ENROLLMENT_SESSION = None

        else:
            result_data = {
                "original_id": msg_id,
                "status": "success",
                "enrollment_stage": "not_started"
            }

    elif operation == "add_clearance":
        #TODO: add a way to add more access areas if we want to later
        user_id = payload.get("unifi_user_id")
        try:
            uaapi.assign_group(user_id, ACCESS_GROUP)
            result_data = {
                "original_id": msg_id,
                "status": "success",
            }
        except:
            result_data = {
                "original_id": msg_id,
                "status": "failure",
                "error": f"Exception in adding group to account",
            }
    
    elif operation == "remove_clearance":
        #TODO: add a way to add more access areas if we want to later
        user_id = payload.get("unifi_user_id")
        try:
            uaapi.unassign_group(user_id, ACCESS_GROUP)
            result_data = {
                "original_id": msg_id,
                "status": "success",
            }
        except:
            result_data = {
                "original_id": msg_id,
                "status": "failure",
                "error": f"Exception in removing group from account",
            }


    # Don't touch clearances, but add a token to the user's account
    elif operation == "add_token":
        user_id = payload.get("unifi_user_id")
        token_id = payload.get("unifi_token_id")
        try:
            uaapi.assign_credential(user_id, token_id)
            result_data = {
                "original_id": msg_id,
                "status": "success",
            }
        except:
            result_data = {
                "original_id": msg_id,
                "status": "failure",
                "error": f"Exception in adding token to account",
            }
    
    # Don't touch clearances, but remove a token from the user's account
    elif operation == "delete_token":
        user_id = payload.get("unifi_user_id")
        token_id = payload.get("unifi_token_id")
        try:
            uaapi.unassign_credential(user_id, token_id)
            result_data = {
                "original_id": msg_id,
                "status": "success",
            }
        except:
            result_data = {
                "original_id": msg_id,
                "status": "failure",
                "error": f"Exception in removing token from account",
            }

    else:
        result_data = {
            "original_id": msg_id,
            "status": "failure",
            "error": f"Unknown operation: {operation}"
        }
    
    return result_data
    

def process_queue():
    logger.info("DHNFCController Worker started. Monitoring queue...")
    
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
