import time
import datetime
import psycopg2
from uhppoted import uhppote
from pprint import pprint

from config import config
from dhs_logging import logger

###############################################################################
# Configuration
###############################################################################

bind = "0.0.0.0"
broadcast = f'255.255.255.255:{config['rfid_board']['BOARD_PORT']}'
listen = f'0.0.0.0:{config['rfid_board']['BOARD_PORT']}'
board_debug = False
# The reason for having the serial number as an integer is that
# uhppote library expects it that way. Got this from the sticker
# on the back of the RFID board and converted it to an integer.
BOARD_SERIAL = int(config['rfid_board']['BOARD_SERIAL_NUMBER_AS_INT'])

# Initialize the uhppote board instance
board = uhppote.Uhppote(bind=bind, 
                        broadcast=broadcast, 
                        listen=listen, 
                        debug=board_debug)

###############################################################################
# Database functions
###############################################################################

def get_db_connection():
    """
    Establishes a connection to the PostgreSQL database.
    """
    
    conn = psycopg2.connect(
        dbname=config['Database']['name'],
        user=config['Database']['user'],
        password=config['Database']['password'],
        host=config['Database']['host'],
        port=config['Database']['port']
    )
    return conn

def close_db_connection(conn):
    """
    Closes the database connection.
    """
    if conn:
        conn.close()
        logger.info("Database connection closed.")
        
def get_last_rfid_event_timestamp(conn):
    """
    Retrieves the timestamp of the latest RFID event from the database.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM member_access_log ORDER BY timestamp DESC LIMIT 1;")
    record = cursor.fetchone()
    cursor.close()
    return record[0] if record else None

def test_db_connection():
    """
    Tests the database connection.
    """
    conn = None
    try:
        conn = get_db_connection()
        logger.info("Database connection successful.")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
    finally:
        close_db_connection(conn)

def insert_rfid_event(conn, event):
    cursor = conn.cursor()
    insert_query = """
        INSERT INTO member_access_log 
        ( 
              member_id,
              rfid_tag,
              access_point,
              access_granted,
              board_tag_num,
              timestamp
        )
        SELECT  g.id,
                g.tag_id,
                %s,
                %s,
                %s,
                %s
        FROM    get_member_by_rfid_tag(%s) g
        ON CONFLICT (rfid_tag, board_tag_num, access_point, access_granted, timestamp)
        DO NOTHING;
    """
    
    cursor.execute(insert_query,
                   (event.door, 
                    event.access_granted, 
                    event.card, 
                    event.timestamp, 
                    event.card))
    conn.commit()
    cursor.close()
    logger.info(f"Inserted event into DB: {event.timestamp}, Door: {event.door}, Type: {event.event_type}, Card: {event.card}, Granted: {event.access_granted}")


###############################################################################
# Board functions
###############################################################################

def get_board_time(max_retries=3):
    """
    Gets the current time from the RFID board with retry logic.
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            response = board.get_time(BOARD_SERIAL)
            return response.datetime.strftime("%m-%d-%Y %H:%M:%S")
        except Exception as e:
            retry_count += 1
            logger.warning(f"Failed to get board time (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                time.sleep(1)
            else:
                raise

def get_events_after(timestamp):
    """
    Retrieves all RFID events from the board after a given timestamp.
    Retries from current position if any error occurs.
    """
    # Get the current event index
    status = board.get_status(BOARD_SERIAL)
    events_index = status.event_index
    
    events_found = 0
    current_index = 0
    max_retries = 3
    
    logger.info(f"Fetching events after {timestamp} (current index: {events_index})")
    
    while current_index < events_index:
        retry_count = 0
        success = False
        # Try to get the event at current_index with retries
        while retry_count < max_retries and not success:
            try:                
                event = board.get_event(BOARD_SERIAL, current_index)
                
                # Check if event has a valid timestamp and the tag number is not 10
                if event.timestamp and event.card != 10:
                    # Only process events with valid event types (not 255)
                    if event.event_type != 255:                                
                        #logger.info(f"{str(event.timestamp):<20} {event.door:<6} {event.event_type:<12} {event.card:<15}")
                        # Check if the event is after the given timestamp
                        if event.timestamp > timestamp:
                            logger.info(f"Adding {str(event.timestamp):<20} {event.door:<6} {event.access_granted:<12} {event.card:<15}")
                            events_found += 1
                            # Now add the event to the database
                            conn = None
                            try:
                                conn = get_db_connection()
                                insert_rfid_event(conn, event)
                            except Exception as e:
                                logger.error(f"Error while inserting event into DB: {e}")
                            finally:
                                close_db_connection(conn)
                
                # Successfully processed this event, move to next
                success = True
                current_index += 1
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Error fetching event at index {current_index}: {e}, attempt {retry_count}/{max_retries}")
                
                if retry_count < max_retries:
                    logger.info(f"Retrying from index {current_index}...")
                    time.sleep(1)  # Brief pause before retry
                else:
                    logger.error(f"Max retries reached for index {current_index}, skipping to next")
                    current_index += 1
                    success = True  # Mark as "success" to move on
                        
    logger.info(f"Total events found after {timestamp}: {events_found}")
    return events_found


################################################################################
# Main function
################################################################################

def main():
    logger.info("Starting rfid2db...")
    logger.info(f"Board Configuration: Serial Number = {BOARD_SERIAL}")
    logger.debug(f"Bind = {bind}, Broadcast = {broadcast}, Listen = {listen}, Debug = {board_debug}")
    
    # Get controller info with retry logic
    max_retries = 3
    retry_count = 0
    record = None
    while retry_count < max_retries and record is None:
        try:
            record = board.get_controller(BOARD_SERIAL)
            pprint(record.__dict__, indent=2, width=1)
        except Exception as e:
            retry_count += 1
            logger.warning(f"Failed to get controller info (attempt {retry_count}/{max_retries}): {e}")
            if retry_count < max_retries:
                time.sleep(2)
            else:
                logger.error("Could not connect to board after multiple attempts")
                raise
    
    logger.info(f"Board time is: {get_board_time()}")
    
    # Test the database connection
    test_db_connection()
    
    # Now let's find out the last time we have an RFID event in the database
    conn = None
    last_event = None
    try:
        conn = get_db_connection()
        last_event_timestamp = get_last_rfid_event_timestamp(conn)
        if last_event_timestamp:
            logger.info(f"Last RFID event in DB at: {last_event_timestamp}")
        else:
            logger.info("No RFID events found in the database.")
    except Exception as e:
        logger.error(f"Error while accessing the database: {e}")
    finally:
        close_db_connection(conn)
    
    # Okay, before we start monitoring, let's see if there are any
    # events on the board we don't have in the database yet.
    if last_event_timestamp:
        get_events_after(last_event_timestamp)
    else:
        logger.info("No previous events found in DB, starting fresh with arbitrary date of 2018-01-01.")
        arbitrary_date = datetime.datetime(2018, 1, 1)
        logger.info(f"Arbitrary start date is: {arbitrary_date}")
        get_events_after(arbitrary_date)

    logger.info("Now monitoring for new RFID events...")
    # Get the current event index to start from
    status = board.get_status(BOARD_SERIAL)
    last_event_index = status.event_index
    max_retries = 3
    
    while True:
        time.sleep(1)  # Polling interval
        retry_count = 0
        success = False
        
        while retry_count < max_retries and not success:
            try:
                status = board.get_status(BOARD_SERIAL)
                current_event_index = status.event_index
                
                if current_event_index > last_event_index:
                    logger.info(f"New events detected: {current_event_index - last_event_index}")
                    event = board.get_event(BOARD_SERIAL, current_event_index)
                    # Log new events
                    conn = None
                    try:
                        conn = get_db_connection()
                        insert_rfid_event(conn, event)
                    except Exception as e:
                        logger.error(f"Error while accessing the database: {e}")
                    finally:
                        close_db_connection(conn)

                    last_event_index = current_event_index
                
                success = True
                
            except Exception as e:
                retry_count += 1
                logger.error(f"Error in monitoring loop: {e}, attempt {retry_count}/{max_retries}")
                
                if retry_count < max_retries:
                    logger.info(f"Retrying connection...")
                    time.sleep(2)  # Brief pause before retry
                else:
                    logger.error(f"Max retries reached, will try again in next iteration")
                    success = True  # Allow loop to continue
            

if __name__ == "__main__":
    main()
