#!/usr/bin/env python3
import os
import traceback
import time
import requests
import select
import psycopg2
import psycopg2.extensions
from contextlib import contextmanager

from config import config
from dhs_logging import logger

###############################################################################
# Configuration
###############################################################################

CHANNEL = config["Database"]["watch_channel"]
BATCH_SIZE = int(config["Database"]["batch_size"])
POLL_INTERVAL = int(config["Database"]["poll_interval"])

# Reconnection/backoff settings
INITIAL_BACKOFF = 1.0
MAX_BACKOFF = 30.0

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
# Job bookkeeping functions - these are the actual SQL operations
# that interact with the member_changes table.
###############################################################################


# This function fetches a batch of unprocessed rows ordered by id
# so that we are always processing in the correct sequence.
def fetch_unprocessed_batch(cur, batch_size, after_id=0):
    cur.execute(
        f"""
        SELECT  * 
        FROM    member_changes
        WHERE   processed = FALSE 
        AND     id > %s
        ORDER BY id
        LIMIT %s
        """,
        (after_id, batch_size),
    )

    if cur.description is None:
        return []

    cols = [desc.name for desc in cur.description]
    rows = cur.fetchall()
    return [dict(zip(cols, row)) for row in rows]


# How many unprocessed rows are there?
def count_unprocessed(cur):
    # How many unprocessed rows are there?
    cur.execute(f"SELECT COUNT(*) FROM member_changes WHERE processed = FALSE")
    count = cur.fetchone()[0]
    logger.info(f"Counted unprocessed rows: {count}")
    return count


# Mark a single row as processed
def mark_as_processed(cur, id_):
    logger.debug(f"Marking row id={id_} as processed.")
    cur.execute(f"UPDATE member_changes SET processed = TRUE WHERE id = %s", (id_,))


# This function is for batch updates of processed rows
def mark_batch_as_processed(cur, ids):
    if not ids:
        return
    logger.debug(f"Marking batch of rows as processed: ids={ids}")
    cur.execute(
        f"UPDATE member_changes SET processed = TRUE WHERE id = ANY(%s)", (ids,)
    )

# This function writes to the member_changes_processing_log table
def log_processing_error(change_row_id, service_name, endpoint, error_code, error_message):
    logger.debug(f"Logging processing error for change row id={change_row_id}: {error_message}")
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO member_changes_processing_log (member_change_id, 
                                                       service_name, 
                                                       service_endpoint, 
                                                       response_code, 
                                                       response_message)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (change_row_id, service_name, endpoint, error_code, error_message),
        )
        conn.commit()
        cur.close()
    logger.debug(f"Logged processing error for change row id={change_row_id}")

###############################################################################
# Services
#   This is where we handle what services to call based on the change data.
###############################################################################


def get_service_for_change(change_type_name):
    # Query the service_endpoints table to find the service responsible
    # for the given change_type.
    # The reason why we do this here instead of hardcoding is to allow
    # dynamic reconfiguration of which service handles which changes.
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, endpoint
            FROM service_endpoints
            WHERE name = %s
            """,
            (change_type_name,),
        )
        result = cur.fetchone()
        if result:
            name, endpoint = result
            return name, endpoint
        else:
            return None, None


###############################################################################
# Processing Logic
###############################################################################


# This is the main processing function for each row.
# If processing fails, return False to indicate a retry is needed.
# Otherwise, return True on success.
def process_row(row):
    logger.info(f"Processing change row id={row['id']}: {row}")

    # We're going to get a payload that tells us what changed
    # and based on that we will invoke the appropriate service.
    data = row.get("data", {})
    # What service to call based on what changed?
    change_type = data.get("change")
    # Now get the service info that we're gonna call
    service_name, endpoint = get_service_for_change(change_type)
    if service_name is None:
        # No service found for this change type - maybe it's new and not yet configured
        # or we dumbly created a change type without a service, which of course couldn't
        # have happened one or sixteen times before.
        logger.error(
            f"No service found for change type '{change_type}'; cannot process change row id={row['id']}."
        )
        return False  # Retry later

    # If we're here, we have a service to call
    logger.info(
        f"Invoking service '{service_name}' at endpoint '{endpoint}' for change type '{change_type}'."
    )
    # Extract relevant data for the service
    member_id = data.get("member_id")
    # Get the specific change data
    change_data = data.get(change_type)

    logger.info(
        f"Preparing to send data to service '{service_name}': member_id={member_id}, change_data={change_data}"
    )

    #
    # Hey! Note that this is not necessarily everything we need to handle this change!
    # For example, an authorization change might mean that we are updating active directory
    # groups, which would require more context (i.e. the member's active directory name).
    # This is not done here, but inside the service itself. The service can query the database
    # for more information as needed. The dispatcher just routes the notification.
    #

    # Send the data to the service endpoint
    # Note that in other environments we may want to do something like put this message on a queue
    # (e.g., AWS SQS, RabbitMQ, etc.) instead of doing a direct HTTP call.

    url = endpoint
    logger.debug(f"Sending POST request to URL: {url}")
    payload = {
        "member_id": member_id,
        "change_type": change_type,
        "change_data": change_data,
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        logger.error(
            f"Failed to process change for change row id={row['id']}: {response.text}" 
        )
        # We need to write this message to the member_changes_processing_log
        # table so DH administrators can see what went wrong.
        log_processing_error(row["id"], service_name, url, response.status_code, response.text)
        return False
    else:
        logger.info(f"Successfully processed change for change row id={row['id']}.")
        # Log success with a null error message
        log_processing_error(row["id"], service_name, url, response.status_code, "Successfully processed.")

    return True


# Process a batch of rows sequentially by id
def process_batch(conn, cur, rows):
    processed_count = 0

    for row_dict in rows:
        row_id = row_dict["id"]

        try:
            success = process_row(row_dict)
            if success:
                mark_as_processed(cur, row_id)
                conn.commit()
                processed_count += 1
                logger.info(f"Marked change row id={row_id} as processed.")
            else:
                logger.info(
                    f"Processing returned False for change row id={row_id}; will retry later."
                )
                conn.rollback()
        except Exception as e:
            logger.error(f"Error processing change row id={row_id}: {e}")
            conn.rollback()
            # Continue with next row; failed row will be retried on next resume

    return processed_count


# Resume processing unprocessed rows on startup/reconnect if for
# any reason DHDispatcher was down and missed notifications.
def resume_unprocessed(conn, cur):
    total_unprocessed = count_unprocessed(cur)
    if total_unprocessed == 0:
        logger.info("No unprocessed rows found.")
        return 0

    logger.info(f"Resuming: found {total_unprocessed} unprocessed row(s).")

    total_processed = 0
    last_id = 0

    while True:
        rows = fetch_unprocessed_batch(cur, BATCH_SIZE, after_id=last_id)

        if not rows:
            break

        logger.info(f"Fetched batch of {len(rows)} row(s) starting after id={last_id}")

        processed_count = process_batch(conn, cur, rows)
        total_processed += processed_count

        # Get the last id from this batch for pagination
        last_id = rows[-1]["id"]

        # If we got fewer rows than batch size, we're done
        if len(rows) < BATCH_SIZE:
            break

    logger.info(f"Resume complete: processed {total_processed} row(s).")
    return total_processed


def process_pending_notifications(conn, cur):
    # Drain all pending notifications first
    conn.poll()
    notification_count = len(conn.notifies)
    conn.notifies.clear()

    if notification_count > 0:
        logger.info(
            f"Received {notification_count} notification(s); processing unprocessed rows..."
        )

    # Fetch and process all unprocessed rows in id order
    # This handles the case where multiple inserts happened and notifications
    # might arrive out of order or be coalesced
    last_id = 0

    while True:
        rows = fetch_unprocessed_batch(cur, BATCH_SIZE, after_id=last_id)

        if not rows:
            break
        logger.info(f"Fetched batch of {len(rows)} row(s) starting after id={last_id}")
        process_batch(conn, cur, rows)

        last_id = rows[-1]["id"]

        if len(rows) < BATCH_SIZE:
            break


###############################################################################
# Main Listener Loop
###############################################################################


def main():
    backoff = INITIAL_BACKOFF

    # Main listener loop with reconnection logic
    while True:
        conn = None
        try:
            with get_db_connection() as conn:
                conn.set_isolation_level(
                    psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED
                )
                cur = conn.cursor()

                # Process any unprocessed rows from previous downtime
                resume_unprocessed(conn, cur)

                # Switch to autocommit for LISTEN
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                cur.execute(f"LISTEN {CHANNEL};")
                logger.info(f"Listening on channel '{CHANNEL}' (fd={conn.fileno()})")

                # Reset backoff on successful connection
                backoff = INITIAL_BACKOFF

                # Main wait loop
                while True:
                    # Wait for notifications; block until data available
                    # Use a timeout to periodically check for unprocessed rows
                    # (handles edge cases where notifications might be missed)
                    ready = select.select([conn], [], [], 60.0)

                    if ready == ([], [], []):
                        # Timeout: do a quick check for any unprocessed rows
                        conn.set_isolation_level(
                            psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED
                        )
                        unprocessed = count_unprocessed(cur)
                        if unprocessed > 0:
                            logger.info(
                                f"Timeout check: found {unprocessed} unprocessed row(s)."
                            )
                            resume_unprocessed(conn, cur)
                        conn.set_isolation_level(
                            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
                        )
                        cur.execute(f"LISTEN {CHANNEL};")
                        continue

                    # Switch to read-committed for processing
                    conn.set_isolation_level(
                        psycopg2.extensions.ISOLATION_LEVEL_READ_COMMITTED
                    )

                    # Process all unprocessed rows in id order
                    process_pending_notifications(conn, cur)

                    # Switch back to autocommit for LISTEN
                    conn.set_isolation_level(
                        psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
                    )
                    cur.execute(f"LISTEN {CHANNEL};")
        except Exception as e:
            logger.error(f"Listener error: {e}")
            
            traceback.print_exc()
            logger.info(f"Reconnecting in {backoff: .1f}s...")
            time.sleep(backoff)
            backoff = min(MAX_BACKOFF, backoff * 2)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    logger.error("Error closing connection")


if __name__ == "__main__":
    main()