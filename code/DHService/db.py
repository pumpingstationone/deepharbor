import psycopg2
from contextlib import contextmanager
import json

from config import config
from dhs_logging import logger
from models import Client

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
# Helpers
###############################################################################

def get_primary_email(payload):
    for email_obj in payload.get("emails", []):
        if email_obj.get("type") == "primary":
            return email_obj.get("email_address")
    return None

def prepare_return_payload(member_id, error_message="OK"):
    return {"member_id": member_id, "message": error_message}

###############################################################################
# Generic Database Operations
###############################################################################

def _get_single_field(member_id: str, field: str):
    """Generic function to get a single field from the member table."""
    logger.debug(f"Getting member {field} for member ID: {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {field} FROM member WHERE id = %s", (member_id,))
            result = cur.fetchone()
    if result:
        return result[0]
    logger.debug(f"No member found with ID: {member_id}")
    return None

def _update_single_field(member_id: int, field: str, value, serialize=True):
    """Generic function to update a single field in the member table."""
    logger.debug(f"Updating member {field} for member ID: {member_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                data = json.dumps(value) if serialize else value
                cur.execute(
                    f"UPDATE member SET {field} = %s WHERE id = %s",
                    (data, member_id),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error updating member {field}: {e}"
        logger.error(error_message)
    return prepare_return_payload(member_id, error_message)

###############################################################################
# Oauth2 Functions
###############################################################################

def get_client_by_client_name(client_name: str) -> Client | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT client_name, client_secret, client_description 
                   FROM oauth2_users WHERE client_name = %s""",
                (client_name,),
            )
            client = cur.fetchone()
    if client is None:
        return None
    return Client(
        client_name=client[0],
        description=client[2],
        enabled=False,
        hashed_password=client[1],
    )

###############################################################################
# Member Database Functions
###############################################################################

def get_member_id_from_email(email_address: str) -> int | None:
    logger.debug(f"Getting member ID from email address: {email_address}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM member
                   WHERE identity->'emails' @> %s::jsonb""",
                (json.dumps([{"type": "primary", "email_address": email_address}]),),
            )
            result = cur.fetchone()
    if result:
        logger.debug(f"Found member ID: {result[0]} for email: {email_address}")
        return result[0]
    logger.debug(f"No member found for email: {email_address}")
    return None

def add_update_identity(identity_dict):
    logger.debug(f"Adding/updating member identity: {identity_dict}")
    email_address = get_primary_email(identity_dict)
    if not email_address:
        error_message = "No primary email address found in payload."
        logger.error(error_message)
        return prepare_return_payload(None, error_message)

    member_id = get_member_id_from_email(email_address)
    error_message = "OK"
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if member_id:
                    cur.execute(
                        "UPDATE member SET identity = %s WHERE id = %s",
                        (json.dumps(identity_dict), member_id),
                    )
                else:
                    cur.execute(
                        "INSERT INTO member (identity) VALUES (%s) RETURNING id",
                        (json.dumps(identity_dict),),
                    )
                    result = cur.fetchone()
                    if result:
                        member_id = result[0]
                    else:
                        raise Exception("Failed to insert new member - no ID returned")
            conn.commit()
    except Exception as e:
        error_message = f"Error adding/updating member identity: {e}"
        logger.error(error_message)
    
    return prepare_return_payload(member_id, error_message)

def change_email_address(email_change_dict):
    old_email = email_change_dict.get("old_email")
    new_email = email_change_dict.get("new_email")
    if not old_email or not new_email:
        error_message = "Both old_email and new_email must be provided."
        logger.error(error_message)
        return prepare_return_payload(None, error_message)

    member_id = get_member_id_from_email(old_email)
    if not member_id:
        error_message = f"No member found with email: {old_email}"
        logger.error(error_message)
        return prepare_return_payload(None, error_message)

    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT identity FROM member WHERE id = %s", (member_id,))
                result = cur.fetchone()
                if not result:
                    raise Exception("Member not found during email change.")
                
                identity = result[0]
                for email_obj in identity.get("emails", []):
                    if email_obj.get("type") == "primary":
                        email_obj["email_address"] = new_email
                
                cur.execute(
                    "UPDATE member SET identity = %s WHERE id = %s",
                    (json.dumps(identity), member_id),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error changing email address: {e}"
        logger.error(error_message)
    
    return prepare_return_payload(member_id, error_message)

def add_update_connections(member_id, connections_dict):
    logger.debug(f"Adding/updating connections for member ID: {member_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT connections FROM member WHERE id = %s", (member_id,))
                result = cur.fetchone()
                existing = result[0] if result and result[0] else {}
                existing.update(connections_dict)
                cur.execute(
                    "UPDATE member SET connections = %s WHERE id = %s",
                    (json.dumps(existing), member_id),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error updating connections: {e}"
        logger.error(error_message)
    return prepare_return_payload(member_id, error_message)

# Simple field update functions using the generic helper
def add_update_forms(member_id, forms_dict):
    return _update_single_field(member_id, "forms", forms_dict)

def add_update_access(member_id, access_dict):
    return _update_single_field(member_id, "access", access_dict)

def add_update_extras(member_id, extras_dict):
    return _update_single_field(member_id, "extras", extras_dict)

def add_update_notes(member_id, notes_dict):
    return _update_single_field(member_id, "notes", notes_dict)

def add_update_status(member_id, status_dict):
    return _update_single_field(member_id, "status", status_dict)

def add_update_authorizations(member_id, authorizations_dict):
    return _update_single_field(member_id, "authorizations", authorizations_dict)

# Simple field getter functions using the generic helper
def get_member_identity(member_id: str) -> dict | None:
    return _get_single_field(member_id, "identity")

def get_member_connections(member_id: str) -> dict | None:
    return _get_single_field(member_id, "connections")

def get_member_status(member_id: str) -> dict | None:
    return _get_single_field(member_id, "status")

def get_member_forms(member_id: str) -> dict | None:
    return _get_single_field(member_id, "forms")

def get_member_access(member_id: str) -> dict | None:
    return _get_single_field(member_id, "access")

def get_member_extras(member_id: str) -> dict | None:
    return _get_single_field(member_id, "extras")

def get_member_authorizations(member_id: str) -> dict | None:
    return _get_single_field(member_id, "authorizations")

def get_member_notes(member_id: str) -> dict | None:
    return _get_single_field(member_id, "notes")

def get_member_last_updated(member_id: str) -> str | None:
    return _get_single_field(member_id, "date_modified")

###############################################################################
# Wild Apricot Sync Functions
###############################################################################

def get_last_wa_sync_time():
    logger.debug("Getting last Wild Apricot sync time.")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_sync_timestamp FROM wild_apricot_sync ORDER BY last_sync_timestamp DESC LIMIT 1"
            )
            result = cur.fetchone()
    return result[0] if result else None

def update_last_wa_sync_time(sync_time):
    logger.debug(f"Updating last Wild Apricot sync time to: {sync_time}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO wild_apricot_sync (id, last_sync_timestamp) VALUES (1, %s)
                       ON CONFLICT (id) DO UPDATE SET last_sync_timestamp = EXCLUDED.last_sync_timestamp""",
                    (sync_time,),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error updating sync time: {e}"
        logger.error(error_message)
    return {"message": error_message}