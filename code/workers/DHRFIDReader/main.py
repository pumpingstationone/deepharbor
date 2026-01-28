import json
import time
import os
import glob
import uuid
import datetime

# The actual library that knows how to talk to the DH2 RFID board
# https://github.com/uhppoted/uhppoted-lib-python
from uhppoted import uhppote

from config import config
from dhs_logging import logger

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
# RFID Board Configuration
###############################################################################

bind = "0.0.0.0"
broadcast = f'255.255.255.255:{config["rfid_board"]["BOARD_PORT"]}'
listen = f'0.0.0.0:{config["rfid_board"]["BOARD_PORT"]}'
board_debug = False
# The reason for having the serial number as an integer is that
# uhppote library expects it that way. Got this from the sticker
# on the back of the RFID board and converted it to an integer.
BOARD_SERIAL_NUM = int(config['rfid_board']['BOARD_SERIAL_NUMBER_AS_INT'])


###############################################################################
# UHPPOTED RFID Board Interaction Functions
###############################################################################

def perform_board_operation(operation: str, tag_id: str = '', converted_tag: str = ''):
    # This function would contain the actual logic to interact with the DH2 RFID board
    # using the uhppoted library. For now, it's just a placeholder.
    logger.info(f"Performing board operation: {operation} on tag_id: {tag_id} with converted_tag: {converted_tag}")

    # Initialize the uhppote board instance
    board = uhppote.Uhppote(bind=bind, 
                            broadcast=broadcast, 
                            listen=listen, 
                            debug=board_debug)

    if operation == "add":
        start_date = datetime.datetime.now()
        end_date = start_date.replace(year=start_date.year + 25)
        # Add the card to the board - we're enabling for all doors, all times
        # which is reprsented as being from now till 25 years from now
        response = board.put_card(BOARD_SERIAL_NUM, 
                                  converted_tag, 
                                  start_date, 
                                  end_date, 
                                  1, 
                                  1, 
                                  1, 
                                  1, 
                                  1)
        logger.info(f"Response from adding card: {response}")
    elif operation == "remove":
        # Remove the card from the board
        board.delete_card(BOARD_SERIAL_NUM, converted_tag)
        logger.info(f"Removed card with converted tag: {converted_tag}")
    else:
        logger.error(f"Unknown operation: {operation}")
        return False

    return True

def set_datetime():
    current_time = datetime.datetime.now()
    logger.info(f"Setting date and time on the board to: {current_time}")
    
    # Initialize the uhppote board instance
    board = uhppote.Uhppote(bind=bind, 
                            broadcast=broadcast, 
                            listen=listen, 
                            debug=board_debug)
    record = board.get_controller(BOARD_SERIAL_NUM)
    logger.info(f"Controller record: {record}")
    
    # We may time out, so keep trying until we get a response
    while True:
        try:            
            set_time_response = board.set_time(BOARD_SERIAL_NUM, current_time)
            break
        except Exception as e:
            logger.warning(f"Timeout getting device info, retrying... Error: {e}")
    
    logger.info(f"Response from setting time: {set_time_response}")

    return {"status": "success", "message": f"Date and time set to {current_time}"}

def get_datetime():
    # Initialize the uhppote board instance
    board = uhppote.Uhppote(bind=bind, 
                            broadcast=broadcast, 
                            listen=listen, 
                            debug=board_debug)
    record = board.get_controller(BOARD_SERIAL_NUM)
    logger.info(f"Controller record: {record}")
    
    # We may time out, so keep trying until we get a response
    while True:
        try:            
            current_time = board.get_time(BOARD_SERIAL_NUM)
            break
        except Exception as e:
            logger.warning(f"Timeout getting device info, retrying... Error: {e}")
    
    logger.info(f"Current date and time from board: {current_time.datetime.strftime('%Y-%m-%d %H:%M:%S')}")    
    return {"status": "success", "current_time": current_time.datetime.strftime('%Y-%m-%d %H:%M:%S')}

###############################################################################
# Message Queue Interaction Functions
###############################################################################

def handle_message(msg_id, payload):
    operation = payload.get("operation")
    tag_id = payload.get("tag_id")
    converted_tag = payload.get("converted_tag")
    
    if operation in ["add", "remove"]:
        success = perform_board_operation(operation, tag_id, converted_tag)
        result_data = {
            "original_id": msg_id,
            "operation": operation,
            "tag_id": tag_id,
            "converted_tag": converted_tag,
            "status": "success" if success else "failure"
        }
    elif operation == "set_datetime":
        result_data = set_datetime()
        result_data["original_id"] = msg_id
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
    logger.info("DHRFIDReader Worker started. Monitoring queue...")
    
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
