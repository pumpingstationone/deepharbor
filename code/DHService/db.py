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

def _update_single_field(member_id: int, field: str, value, serialize=True, last_updated_by=None):
    """Generic function to update a single field in the member table."""
    logger.debug(f"Updating member {field} for member ID: {member_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                data = json.dumps(value) if serialize else value
                if last_updated_by is not None:
                    cur.execute(
                        f"UPDATE member SET {field} = %s, last_updated_by = %s WHERE id = %s",
                        (data, last_updated_by, member_id),
                    )
                else:
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

def search_members(query: str) -> list[dict]:
    logger.debug(f"Searching members with query: {query}")
    members = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,
                          identity ->> 'first_name' first_name,
                          identity ->> 'last_name' last_name,
                          identity -> 'emails' -> 0 ->> 'email_address' primary_email_address
                   FROM   search_members(%s)
                """,
                (query,),
            )
            results = cur.fetchall()
    for result in results:
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3]
        })
    logger.debug(f"Found {len(members)} members matching query: {query}")
    return members

def search_members_by_identity_and_access(query: str) -> list[dict]:
    logger.debug(f"Searching members with query: {query}")
    members = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,
                          identity ->> 'first_name' first_name,
                          identity ->> 'last_name' last_name,
                          identity -> 'emails' -> 0 ->> 'email_address' primary_email_address
                   FROM   search_members_by_identity_and_access(%s)
                """,
                (query,),
            )
            results = cur.fetchall()
    for result in results:
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3]
        })
    logger.debug(f"Found {len(members)} members matching query: {query}")
    return members

def add_update_identity(identity_dict):
    logger.debug(f"Adding/updating member identity: {identity_dict}")
    
    # Extract modified_by if present and identity_dict is a dictionary
    last_updated_by = None
    if isinstance(identity_dict, dict):
        last_updated_by = identity_dict.pop("modified_by", None)
    
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
                    if last_updated_by is not None:
                        cur.execute(
                            "UPDATE member SET identity = %s, last_updated_by = %s WHERE id = %s",
                            (json.dumps(identity_dict), last_updated_by, member_id),
                        )
                    else:
                        cur.execute(
                            "UPDATE member SET identity = %s WHERE id = %s",
                            (json.dumps(identity_dict), member_id),
                        )
                else:
                    if last_updated_by is not None:
                        cur.execute(
                            "INSERT INTO member (identity, last_updated_by) VALUES (%s, %s) RETURNING id",
                            (json.dumps(identity_dict), last_updated_by),
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
    
    # Extract modified_by if present and connections_dict is a dictionary
    last_updated_by = None
    if isinstance(connections_dict, dict):
        last_updated_by = connections_dict.pop("modified_by", None)
    
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT connections FROM member WHERE id = %s", (member_id,))
                result = cur.fetchone()
                existing = result[0] if result and result[0] else {}
                existing.update(connections_dict)
                if last_updated_by is not None:
                    cur.execute(
                        "UPDATE member SET connections = %s, last_updated_by = %s WHERE id = %s",
                        (json.dumps(existing), last_updated_by, member_id),
                    )
                else:
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
    last_updated_by = forms_dict.pop("modified_by", None) if isinstance(forms_dict, dict) else None
    return _update_single_field(member_id, "forms", forms_dict, last_updated_by=last_updated_by)

def add_update_access(member_id, access_dict):
    last_updated_by = access_dict.pop("modified_by", None) if isinstance(access_dict, dict) else None
    return _update_single_field(member_id, "access", access_dict, last_updated_by=last_updated_by)

def add_update_extras(member_id, extras_dict):
    last_updated_by = extras_dict.pop("modified_by", None) if isinstance(extras_dict, dict) else None
    return _update_single_field(member_id, "extras", extras_dict, last_updated_by=last_updated_by)

def add_update_notes(member_id, notes_dict):
    last_updated_by = notes_dict.pop("modified_by", None) if isinstance(notes_dict, dict) else None
    return _update_single_field(member_id, "notes", notes_dict, last_updated_by=last_updated_by)

def add_update_status(member_id, status_dict):
    last_updated_by = status_dict.pop("modified_by", None) if isinstance(status_dict, dict) else None
    return _update_single_field(member_id, "status", status_dict, last_updated_by=last_updated_by)

def add_update_authorizations(member_id, authorizations_dict):
    last_updated_by = authorizations_dict.pop("modified_by", None) if isinstance(authorizations_dict, dict) else None
    return _update_single_field(member_id, "authorizations", authorizations_dict, last_updated_by=last_updated_by)

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

# This gets the roles assigned to a member for things like using the admin portal
# This can return null or an empty list if no roles are assigned
def get_member_roles(member_id: str) -> list[str]:
    logger.debug(f"Getting roles for member ID: {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """ SELECT     r.name, 
                               r.permission
                    FROM       roles r 
                    INNER JOIN member_to_role mtr ON mtr.role_id = r.id 
                    AND        mtr.member_id = %s""",
                (member_id,),
            )
            results = cur.fetchall()
    # We have to get the role name and the permissions to send back
    roles = []
    for result in results:
        role_name = result[0]
        permission = result[1]
        roles.append({"role_name": role_name, "permission": permission})
        
    logger.debug(f"Member ID: {member_id} has roles: {roles}")
    return roles

def get_full_member_info(member_id: str) -> dict:
    logger.debug(f"Getting full member info for member ID: {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """ SELECT   member_info
                    FROM     v_member_info
                    WHERE    member_id = %s;
                """,
                (member_id,),
            )
            result = cur.fetchone()
    if result:
        # We just want to return the JSON object directly
        return result[0]
    logger.debug(f"No member found with ID: {member_id}")
    return {}

def get_member_entry_logs(member_id: str) -> list[dict]:
    logger.debug(f"Getting entry logs for member ID: {member_id}")
    entry_logs = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """ 
                SELECT   mal.timestamp,
                         CASE
                                WHEN mal.access_point = '1' 
                                THEN 'Front Door'
                                WHEN mal.access_point = '2' 
                                THEN 'Back Door'
                                ELSE 'Unknown'
                         END AS access_point,
                         CASE
                                WHEN mal.access_granted 
                                THEN 'GRANTED'
                                ELSE 'DENIED'
                         END AS access_granted,
                         mal.rfid_tag
                FROM     member_access_logs mal
                WHERE    mal.member_id = %s
                ORDER BY mal.timestamp DESC;
                """,
                (member_id,),
            )
            results = cur.fetchall()
    for result in results:
        entry_logs.append({
            "timestamp": result[0],
            "access_point": result[1],
            "access_granted": result[2],
            "rfid_tag": result[3],
        })
        
    logger.debug(f"Retrieved {len(entry_logs)} entry logs for member ID: {member_id}")
    return entry_logs


# This has been a problem for years, so we add a dedicated function to check username availability
# so we don't end up with screwed up active directory accounts, B2C logins and upset members.
def is_username_available(username: str) -> bool:
    logger.debug(f"Checking availability of username: {username}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(1) FROM member WHERE identity->>'active_directory_username' = %s",
                (username,),
            )
            result = cur.fetchone()
        if not result:
            logger.debug(f"Username: {username} is available: True")
            return True
    available = result[0] == 0
    logger.debug(f"Username: {username} available: {available}")
    return available    

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

###############################################################################
# Bulk Database Functions
###############################################################################
def get_all_member_names_and_emails() -> list[dict]:
    logger.debug("Getting names and email addresses for all members.")
    members = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,
                          identity ->> 'first_name' AS first_name,
                          identity ->> 'last_name' AS last_name,
                          identity -> 'emails' -> 0 ->> 'email_address' AS primary_email_address
                   FROM member"""
            )
            results = cur.fetchall()
    for result in results:
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3]
        })
    logger.debug(f"Retrieved {len(members)} members from the database.")
    return members

def get_available_authorizations() -> list[dict]:
    logger.debug("Getting all available equipment.")
    equipment = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description, requires_login
                   FROM available_authorizations"""
            )
            results = cur.fetchall()
    for result in results:
        equipment.append({
            "equipment_id": result[0],
            "name": result[1],
            "description": result[2],
            "requires_login": result[3],
        })
    logger.debug(f"Retrieved {len(equipment)} available authorizations from the database.")
    return equipment

###############################################################################
# Deep Harbor specific database functions (e.g. user activity on websites)
###############################################################################
def log_user_activity(activity_data: dict):
    # Get the member ID from the activity data
    member_id = activity_data.get("member_id")
    
    logger.debug(f"Logging user activity for member ID: {member_id} with data: {activity_data}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO user_activity_logs (member_id, activity_details, timestamp)
                       VALUES (%s, %s, NOW())""",
                    (member_id, json.dumps(activity_data.get("activity_details"))),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error logging user activity: {e}"
        logger.error(error_message)
    return {"message": error_message}

# Contacts database functions
def search_contacts_by_email(email_address: str) -> list[dict]:
    logger.debug(f"Searching for a contact with the email address: {email_address}")
    contacts = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id,
                          first_name,
                          last_name,
                          email_address,
                          phone_number,
                          signed_at_datetime
                   FROM   v_waivers
                   WHERE  email_address ILIKE %s
                   limit 1;
                """,
                (email_address,),
            )
            results = cur.fetchall()
    for result in results:
        # Wrap this result under 'contact'
        contact = {
            "contact_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3],
            "phone_number": result[4],
            "signed_at_datetime": result[5],
        }
        contacts.append({"contact": contact})
    logger.debug(f"Found {len(contacts)} contacts matching email address: {email_address}")
    return contacts