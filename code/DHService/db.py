import math
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

ALLOWED_MEMBER_FIELDS = {
    "identity", "connections", "status", "forms",
    "access", "extras", "authorizations", "notes", "date_modified",
}

def _get_single_field(member_id: str, field: str):
    """Generic function to get a single field from the member table."""
    if field not in ALLOWED_MEMBER_FIELDS:
        raise ValueError(f"Invalid field: {field}")
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
    """Generic function to REPLACE a single field in the member table.

    Use this only for non-object JSONB columns (e.g. notes, which is an
    array and is built-up in Python before write). For object-shaped JSONB
    columns (identity, status, forms, access, extras, authorizations,
    connections), use `_merge_jsonb_field` so partial POSTs don't wipe
    keys the caller didn't supply.
    """
    if field not in ALLOWED_MEMBER_FIELDS:
        raise ValueError(f"Invalid field: {field}")
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

def _merge_jsonb_field(member_id: int, field: str, value: dict, last_updated_by=None):
    """Shallow-merge `value` into the existing JSONB column `field` on member.

    Uses Postgres `||` operator for atomic single-statement merge. Top-level
    keys in `value` overwrite matching keys in the existing column; keys not
    present in `value` are preserved. Works correctly when the column is NULL
    (treated as `{}`).

    Caveats:
    - Shallow merge only — array values inside the blob are replaced wholesale
      (e.g. `emails`, `rfid_tags`). Every existing caller sends full arrays,
      so this matches intent.
    - Cannot remove keys. To delete a key, callers would need a dedicated
      delete endpoint (none exists today; add when needed).
    - Only valid for object-shaped JSONB columns. Do NOT call this for `notes`
      (array): `||` on arrays concatenates instead of merging, which would
      double-append since `add_update_notes` builds the full list.
    """
    if field not in ALLOWED_MEMBER_FIELDS:
        raise ValueError(f"Invalid field: {field}")
    logger.debug(f"Merging into member {field} for member ID: {member_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                payload = json.dumps(value)
                if last_updated_by is not None:
                    cur.execute(
                        f"UPDATE member "
                        f"SET    {field} = COALESCE({field}, '{{}}'::jsonb) || %s::jsonb, "
                        f"       last_updated_by = %s "
                        f"WHERE  id = %s",
                        (payload, last_updated_by, member_id),
                    )
                else:
                    cur.execute(
                        f"UPDATE member "
                        f"SET    {field} = COALESCE({field}, '{{}}'::jsonb) || %s::jsonb "
                        f"WHERE  id = %s",
                        (payload, member_id),
                    )
            conn.commit()
    except Exception as e:
        error_message = f"Error merging member {field}: {e}"
        logger.error(error_message)
    return prepare_return_payload(member_id, error_message)

###############################################################################
# Oauth2 Functions
###############################################################################

def get_client_by_client_name(client_name: str) -> Client | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, client_name, client_secret, client_description, disabled
                   FROM oauth2_users WHERE client_name = %s""",
                (client_name,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return Client(
        id=row[0],
        client_name=row[1],
        hashed_password=row[2],
        description=row[3],
        disabled=row[4],
    )


###############################################################################
# Oauth2 admin functions (API client management)
###############################################################################

def _row_to_api_client(row) -> dict:
    return {
        "id": row[0],
        "client_name": row[1],
        "client_description": row[2],
        "disabled": row[3],
        "date_added": row[4],
        "created_by_member_id": row[5],
        "last_used_at": row[6],
        "rotated_at": row[7],
        "created_by_first_name": row[8],
        "created_by_last_name": row[9],
    }


# LEFT JOIN against member so a deleted/missing creator still returns the row
# with null name fields rather than dropping it from the listing.
_API_CLIENT_SELECT = """
    SELECT o.id, o.client_name, o.client_description, o.disabled,
           o.date_added, o.created_by_member_id, o.last_used_at, o.rotated_at,
           m.identity->>'first_name' AS created_by_first_name,
           m.identity->>'last_name'  AS created_by_last_name
      FROM oauth2_users o
      LEFT JOIN member m ON m.id = o.created_by_member_id
"""


def list_api_clients() -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{_API_CLIENT_SELECT} ORDER BY o.client_name")
            rows = cur.fetchall()
    return [_row_to_api_client(r) for r in rows]


def get_api_client(client_id: int) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{_API_CLIENT_SELECT} WHERE o.id = %s", (client_id,))
            row = cur.fetchone()
    return _row_to_api_client(row) if row else None


def create_api_client(
    client_name: str,
    client_secret_hash: str,
    client_description: str | None,
    created_by_member_id: int | None,
) -> dict:
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO oauth2_users
                       (client_name, client_secret, client_description, created_by_member_id)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (client_name, client_secret_hash, client_description, created_by_member_id),
                )
                new_id = cur.fetchone()[0]
                conn.commit()
        return {"id": new_id, "message": "OK"}
    except psycopg2.errors.UniqueViolation:
        logger.info(f"create_api_client rejected duplicate client_name: {client_name}")
        return {"id": None, "message": "client_name already exists"}
    except Exception as e:
        logger.error(f"create_api_client failed for {client_name}: {e}")
        return {"id": None, "message": f"create failed: {e}"}


def update_api_client_secret(client_id: int, client_secret_hash: str) -> dict:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE oauth2_users
                   SET client_secret = %s, rotated_at = NOW()
                 WHERE id = %s""",
                (client_secret_hash, client_id),
            )
            updated = cur.rowcount
            conn.commit()
    return {"id": client_id, "updated": updated}


# Allowlist for patch_api_client — mirrors the FIELD_VALIDATORS allowlist pattern
# used elsewhere in the codebase (CLAUDE.md: "always use the allowlist pattern
# for SQL column interpolation").
_API_CLIENT_PATCH_COLUMNS = {"disabled", "client_description"}


def patch_api_client(
    client_id: int,
    disabled: bool | None,
    client_description: str | None,
) -> dict:
    updates: dict[str, object] = {}
    if disabled is not None:
        updates["disabled"] = disabled
    if client_description is not None:
        updates["client_description"] = client_description
    if not updates:
        return {"id": client_id, "updated": 0}
    for col in updates:
        if col not in _API_CLIENT_PATCH_COLUMNS:
            raise ValueError(f"column {col!r} is not patchable")
    set_clause = ", ".join(f"{col} = %s" for col in updates)
    params = list(updates.values()) + [client_id]
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE oauth2_users SET {set_clause} WHERE id = %s",
                params,
            )
            updated = cur.rowcount
            conn.commit()
    return {"id": client_id, "updated": updated}


def touch_last_used(client_name: str) -> None:
    """Best-effort UPDATE of last_used_at on /token success.
    Must not raise — it sits in the hot path of authentication.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE oauth2_users SET last_used_at = NOW() WHERE client_name = %s",
                    (client_name,),
                )
                conn.commit()
    except Exception as e:
        logger.error(f"touch_last_used failed for {client_name}: {e}")

###############################################################################
# Member Database Functions
###############################################################################

def get_member_id_from_email(email_address: str) -> int | None:
    logger.debug(f"Getting member ID from email address: {email_address}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id FROM member
                   WHERE EXISTS (
                       SELECT 1 FROM jsonb_array_elements(identity->'emails') AS e
                       WHERE LOWER(e->>'email_address') = LOWER(%s)
                         AND e->>'type' = 'primary')""",
                (email_address,),
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
                          identity -> 'emails' -> 0 ->> 'email_address' primary_email_address,
                          status ->> 'membership_status' membership_status
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
            "primary_email_address": result[3],
            "membership_status": result[4]
        })
    logger.debug(f"Found {len(members)} members matching query: {query}")
    return members

###############################################################################
# Paginated Member Listing
###############################################################################

# Allowlist for ORDER BY columns — maps API param names to SQL expressions.
# Direct column interpolation into SQL is safe ONLY through this allowlist.
_MEMBER_SORT_COLUMNS = {
    "date_added": "m.date_added",
    "id": "m.id",
    "first_name": "m.identity ->> 'first_name'",
    "last_name": "m.identity ->> 'last_name'",
    "membership_status": "m.status ->> 'membership_status'",
}

# Search CTE uses plain column names (no table prefix, no date_added)
_SEARCH_SORT_COLUMNS = {
    "rank": "rank",
    "id": "id",
    "first_name": "first_name",
    "last_name": "last_name",
    "membership_status": "membership_status",
}

def _validate_sort(sort: str, order: str, allowlist: dict, default_sort: str) -> tuple[str, str]:
    col = allowlist.get(sort, allowlist[default_sort])
    direction = "ASC" if order.lower() == "asc" else "DESC"
    return col, direction

def _paginated_response(members: list[dict], total: int, page: int, per_page: int) -> dict:
    return {
        "members": members,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, math.ceil(total / per_page)),
    }

def list_members(page: int = 1, per_page: int = 25,
                 sort: str = "date_added", order: str = "desc") -> dict:
    logger.debug(f"Listing members page={page} per_page={per_page} sort={sort} order={order}")
    sort_col, direction = _validate_sort(sort, order, _MEMBER_SORT_COLUMNS, "date_added")
    offset = (page - 1) * per_page

    members = []
    total = 0
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT m.id,
                           m.identity ->> 'first_name' AS first_name,
                           m.identity ->> 'last_name' AS last_name,
                           m.identity -> 'emails' -> 0 ->> 'email_address' AS primary_email_address,
                           m.status ->> 'membership_status' AS membership_status,
                           m.status ->> 'stripe_product_id' AS stripe_product_id,
                           COUNT(*) OVER() AS total_count
                    FROM   member m
                    ORDER BY {sort_col} {direction}
                    LIMIT  %s OFFSET %s
                """,
                (per_page, offset),
            )
            results = cur.fetchall()

    for result in results:
        total = result[6]
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3],
            "membership_status": result[4],
            "stripe_product_id": result[5],
        })

    logger.debug(f"Listed {len(members)} members (total={total})")
    return _paginated_response(members, total, page, per_page)

def search_members_paginated(query: str, page: int = 1, per_page: int = 25,
                             sort: str = "rank", order: str = "desc") -> dict:
    logger.debug(f"Paginated search query={query} page={page} per_page={per_page} sort={sort} order={order}")
    sort_col, direction = _validate_sort(sort, order, _SEARCH_SORT_COLUMNS, "rank")
    offset = (page - 1) * per_page

    members = []
    total = 0
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""WITH results AS (
                        SELECT id,
                               identity ->> 'first_name' AS first_name,
                               identity ->> 'last_name' AS last_name,
                               identity -> 'emails' -> 0 ->> 'email_address' AS primary_email_address,
                               status ->> 'membership_status' AS membership_status,
                               status ->> 'stripe_product_id' AS stripe_product_id,
                               rank
                        FROM   search_members_by_identity_and_access(%s)
                    )
                    SELECT *, COUNT(*) OVER() AS total_count
                    FROM   results
                    ORDER BY {sort_col} {direction}
                    LIMIT  %s OFFSET %s
                """,
                (query, per_page, offset),
            )
            results = cur.fetchall()

    for result in results:
        total = result[7]
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3],
            "membership_status": result[4],
            "stripe_product_id": result[5],
        })

    logger.debug(f"Paginated search found {len(members)} members (total={total})")
    return _paginated_response(members, total, page, per_page)

def add_update_identity(identity_dict, member_id=None):
    # When member_id is provided by the caller (standard update path), update
    # that row directly. Email-based lookup is only used as a fallback for the
    # signup path where the caller does not yet have a member_id. Looking up
    # by email for updates is unsafe because multiple members can share an
    # email (seed data, race conditions), and SELECT ... fetchone() returns
    # a non-deterministic row — which would overwrite the wrong member.
    logger.debug(f"Adding/updating member identity for member_id={member_id}: {identity_dict}")

    # Extract modified_by if present and identity_dict is a dictionary
    last_updated_by = None
    if isinstance(identity_dict, dict):
        last_updated_by = identity_dict.pop("modified_by", None)

    caller_provided_member_id = member_id is not None
    if caller_provided_member_id and member_id <= 0:
        error_message = f"Invalid member_id: {member_id} (must be positive)."
        logger.error(error_message)
        return prepare_return_payload(None, error_message)

    if not caller_provided_member_id:
        email_address = get_primary_email(identity_dict)
        if not email_address:
            error_message = "No primary email address found in payload and no member_id provided."
            logger.error(error_message)
            return prepare_return_payload(None, error_message)
        member_id = get_member_id_from_email(email_address)

    error_message = "OK"

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if member_id is not None:
                    # Shallow JSONB merge so a partial POST (e.g. just
                    # `{"birthday": ...}`) doesn't wipe other identity
                    # keys. See GH #263. The `emails` array key is
                    # replaced wholesale on merge, which matches every
                    # caller's intent (they always send full arrays).
                    if last_updated_by is not None:
                        cur.execute(
                            "UPDATE member "
                            "SET    identity = COALESCE(identity, '{}'::jsonb) || %s::jsonb, "
                            "       last_updated_by = %s "
                            "WHERE  id = %s",
                            (json.dumps(identity_dict), last_updated_by, member_id),
                        )
                    else:
                        cur.execute(
                            "UPDATE member "
                            "SET    identity = COALESCE(identity, '{}'::jsonb) || %s::jsonb "
                            "WHERE  id = %s",
                            (json.dumps(identity_dict), member_id),
                        )
                    if cur.rowcount == 0:
                        error_message = f"No member found with id {member_id}; nothing updated."
                        logger.warning(error_message)
                        return prepare_return_payload(None, error_message)
                else:
                    # Signup path: no caller member_id and email lookup found
                    # no match — INSERT the full blob. No row to merge into.
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
    last_updated_by = connections_dict.pop("modified_by", None) if isinstance(connections_dict, dict) else None
    return _merge_jsonb_field(member_id, "connections", connections_dict, last_updated_by=last_updated_by)

# Object-shaped JSONB update functions — use `_merge_jsonb_field` so partial
# POSTs don't wipe keys the caller didn't supply. See GH #263 for the bug
# class this prevents.
def add_update_forms(member_id, forms_dict):
    last_updated_by = forms_dict.pop("modified_by", None) if isinstance(forms_dict, dict) else None
    return _merge_jsonb_field(member_id, "forms", forms_dict, last_updated_by=last_updated_by)

def add_update_access(member_id, access_dict):
    last_updated_by = access_dict.pop("modified_by", None) if isinstance(access_dict, dict) else None
    return _merge_jsonb_field(member_id, "access", access_dict, last_updated_by=last_updated_by)

def add_update_extras(member_id, extras_dict):
    last_updated_by = extras_dict.pop("modified_by", None) if isinstance(extras_dict, dict) else None
    return _merge_jsonb_field(member_id, "extras", extras_dict, last_updated_by=last_updated_by)

def add_update_notes(member_id, notes_dict):
    last_updated_by = notes_dict.pop("modified_by", None) if isinstance(notes_dict, dict) else None
    if notes_dict is None or (isinstance(notes_dict, str) and not notes_dict.strip()) or (isinstance(notes_dict, dict) and not notes_dict):
        return prepare_return_payload(member_id, "No note provided.")
    # Notes are a special case because we want to append new notes to
    # existing notes rather than replace them, so we need to get the
    # existing notes, append the new note, and then update the field
    # with the combined notes.
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT notes FROM member WHERE id = %s", (member_id,))
            result = cur.fetchone()
            existing_notes = result[0] if result and result[0] else []
            # Normalize existing notes into a list of note objects.
            if isinstance(existing_notes, dict):
                existing_notes = [existing_notes]
            elif isinstance(existing_notes, str):
                existing_notes = [{"note": existing_notes}]

            # Normalize incoming note into a note object.
            if isinstance(notes_dict, dict):
                new_note = notes_dict
            else:
                new_note = {"note": notes_dict}

            existing_notes.append(new_note)
    return _update_single_field(member_id, "notes", existing_notes, last_updated_by=last_updated_by)

def add_update_status(member_id, status_dict):
    last_updated_by = status_dict.pop("modified_by", None) if isinstance(status_dict, dict) else None
    return _merge_jsonb_field(member_id, "status", status_dict, last_updated_by=last_updated_by)

def add_update_authorizations(member_id, authorizations_dict):
    last_updated_by = authorizations_dict.pop("modified_by", None) if isinstance(authorizations_dict, dict) else None
    return _merge_jsonb_field(member_id, "authorizations", authorizations_dict, last_updated_by=last_updated_by)

def get_member_authorization_changes(member_id: str) -> dict:
    logger.debug(f"Getting authorization changes for member ID: {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT get_authorization_changes_for_member(%s)", (member_id,))
            result = cur.fetchone()
    if result:
        return result[0]
    logger.debug(f"No member found with ID: {member_id} for authorization changes")
    return {"member_id": member_id, "added": [], "removed": []}

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

def search_onboarder_candidates(query: str, limit: int = 20) -> list[dict]:
    """Search members by name/username for the onboarder picker.

    Ranks members holding the `member.forms` change permission first (via any
    role they hold), then alphabetical by last_name, first_name. Returns at
    most `limit` rows. Used by the admin portal Onboard tab and Forms tab
    onboarder picker.
    """
    logger.debug(f"Searching onboarder candidates for query: {query!r}")
    # Escape ILIKE wildcards in user input so a literal `%` or `_` doesn't
    # silently turn into a wildcard match. `\` itself is also escaped so
    # `\%` typed by the user isn't treated as our escape sequence.
    if query:
        cleaned = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{cleaned}%"
    else:
        pattern = "%"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id,
                       m.identity ->> 'first_name'                AS first_name,
                       m.identity ->> 'last_name'                 AS last_name,
                       m.identity ->> 'active_directory_username' AS username,
                       COALESCE(BOOL_OR(r.permission -> 'change' ? 'member.forms'), FALSE)
                                                                  AS has_forms_change_perm
                FROM       member m
                LEFT JOIN  member_to_role mtr ON mtr.member_id = m.id
                LEFT JOIN  roles r            ON r.id = mtr.role_id
                WHERE      m.identity ->> 'first_name' ILIKE %s
                       OR  m.identity ->> 'last_name'  ILIKE %s
                       OR  m.identity ->> 'active_directory_username' ILIKE %s
                GROUP BY   m.id
                ORDER BY   has_forms_change_perm DESC,
                           LOWER(m.identity ->> 'last_name')  ASC NULLS LAST,
                           LOWER(m.identity ->> 'first_name') ASC NULLS LAST
                LIMIT      %s
                """,
                (pattern, pattern, pattern, limit),
            )
            rows = cur.fetchall()
    return [
        {
            "member_id": row[0],
            "first_name": row[1],
            "last_name": row[2],
            "username": row[3],
            "has_forms_change_perm": row[4],
        }
        for row in rows
    ]


def resolve_member_display_name(member_id: int) -> dict | None:
    """Return identity name fields for a single member, or None if not found.

    Used by the admin portal Forms tab and the member portal storage card to
    render the onboarder name from a stored `id_check_by` member_id.
    """
    logger.debug(f"Resolving display name for member ID: {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """ SELECT m.id,
                           m.identity ->> 'first_name',
                           m.identity ->> 'last_name',
                           m.identity ->> 'active_directory_username'
                    FROM   member m
                    WHERE  m.id = %s
                """,
                (member_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "member_id": row[0],
        "first_name": row[1],
        "last_name": row[2],
        "username": row[3],
    }


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
                FROM     member_access_log mal
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

def get_member_by_stripe_customer_id(stripe_customer_id: str) -> dict | None:
    logger.debug(f"Getting member by Stripe customer ID: {stripe_customer_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, first_name, last_name, primary_email, membership_status 
                FROM   v_member_name_email_status 
                WHERE  id = (SELECT id 
                FROM   member
                WHERE  connections->>'stripe_id' = %s );
                """,
                (stripe_customer_id,),
            )
            result = cur.fetchone()
    if result:
        member_id = result[0]
        identity = {"first_name": result[1], "last_name": result[2], "primary_email": result[3], "membership_status": result[4]}
        logger.debug(f"Found member ID: {member_id} for Stripe customer ID: {stripe_customer_id}")
        return {"member_id": member_id, "identity": identity}
    logger.debug(f"No member found with Stripe customer ID: {stripe_customer_id}")
    return None

# This has been a problem for years, so we add a dedicated function to check username availability
# so we don't end up with screwed up active directory accounts, B2C logins and upset members.
def is_username_available(username: str) -> bool:
    logger.debug(f"Checking availability of username: {username}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(1) FROM member WHERE LOWER(identity->>'active_directory_username') = LOWER(%s)",
                (username,),
            )
            result = cur.fetchone()
        if not result:
            logger.debug(f"Username: {username} is available: True")
            return True
    available = result[0] == 0
    logger.debug(f"Username: {username} available: {available}")
    return available    

def search_members_by_rfid_tag(rfid_tag: str) -> list[dict]:
    logger.debug(f"Searching for a member with RFID tag: {rfid_tag}")
    members = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT m.id,
                       m.identity ->> 'first_name' AS first_name,
                       m.identity ->> 'last_name' AS last_name,
                       m.identity ->> 'nickname' AS nickname,
                       m.identity ->> 'pronouns' AS pronouns,
                       m.identity ->> 'nametag_subtitle' as nametag_subtitle,
                       m.identity ->> 'theme_song_url' as theme_song_url,
                       m.identity ->> 'theme_song_duration' as theme_song_duration,
                       v.primary_email AS primary_email_address
                FROM   member m, 
                       v_member_id_email v,
                       jsonb_array_elements_text(m.access -> 'rfid_tags') AS tag
                WHERE  ltrim(tag, '0') = ltrim(%s, '0')
                AND    m.id = v.id;                
                """,
                (rfid_tag,),
            )
            results = cur.fetchall()
    for result in results:
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "nickname": result[3],
            "pronouns": result[4],
            "nametag_subtitle": result[5],
            "theme_song_url": result[6],
            "theme_song_duration": result[7],
            "primary_email_address": result[8]
        })
    logger.debug(f"Found {len(members)} members with RFID tag: {rfid_tag}")
    return members

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
def get_active_member_names_and_emails() -> list[dict]:
    logger.debug("Getting names and email addresses for all active members.")
    members = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id,
                          identity ->> 'first_name' AS first_name,
                          identity ->> 'last_name' AS last_name,
                          identity -> 'emails' -> 0 ->> 'email_address' AS primary_email_address
                   FROM member
                   WHERE status ->> 'membership_status' = 'active'
                """
            )
            results = cur.fetchall()
    for result in results:
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email_address": result[3]
        })
    logger.debug(f"Retrieved {len(members)} active members from the database.")
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
# Deep Harbor specific database functions (e.g. user activity on websites,
# product lookups, etc.)
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

def get_available_membership_levels() -> list[dict]:
    logger.debug("Getting all available membership levels.")
    membership_levels = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description
                   FROM membership_types_lookup order by name"""
            )
            results = cur.fetchall()
    for result in results:
        membership_levels.append({
            "membership_level_id": result[0],
            "name": result[1],
            "description": result[2],
        })
    logger.debug(f"Retrieved {len(membership_levels)} available membership levels from the database.")
    return membership_levels

def save_stripe_event(event: dict):
    logger.debug(f"Saving Stripe event to the database: {event}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                event_sql = """
                    INSERT INTO subscriptions (details)
                    VALUES (%s)
                """
                cur.execute(event_sql, (json.dumps(event),))
            conn.commit()
    except Exception as e:
        error_message = f"Error saving Stripe event: {e}"
        logger.error(error_message)
    return {"message": error_message}

# "Products" in this case are the different subscription options we have in 
# Stripe, which we want to be able to look up and send to whatever, like
# ST2DH, that needs to know about them. This is a simple lookup function that
# gets the product information from the database and it's assumed the
# caller will know what to do with it (e.g. send it to ST2DH, use it 
# to match against incoming Stripe events, etc.)
def get_products() -> list[dict]:
    logger.debug("Getting all products from the database.")
    products = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description, details
                   FROM products"""
            )
            results = cur.fetchall()
    for result in results:
        products.append({
            "product_id": result[0],
            "name": result[1],
            "description": result[2],
            "details": result[3],        
            })
    logger.debug(f"Retrieved {len(products)} products from the database.")
    return products

###############################################################################
# Space functions (access logs, etc.)
###############################################################################

def get_access_logs(start_date: str, end_date: str) -> list[dict]:
    logger.debug(f"Getting access logs from {start_date} to {end_date}")
    logs = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT   mal.timestamp,
                         m.identity ->> 'first_name' AS first_name,
                         m.identity ->> 'last_name' AS last_name,
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
                         mal.rfid_tag,
                         mal.member_id
                FROM     member_access_log mal
                LEFT JOIN member m ON m.id = mal.member_id
                WHERE    mal.timestamp >= %s::date
                AND      mal.timestamp < %s::date + INTERVAL '1 day'
                ORDER BY mal.timestamp DESC;
                """,
                (start_date, end_date),
            )
            results = cur.fetchall()
    for result in results:
        logs.append({
            "timestamp": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "access_point": result[3],
            "access_granted": result[4],
            "rfid_tag": result[5],
            "member_id": result[6],
        })
    logger.debug(f"Retrieved {len(logs)} access log entries.")
    return logs

###############################################################################
# Admin functions (roles management, etc.)
###############################################################################

def get_all_roles() -> list[dict]:
    logger.debug("Getting all roles from the database.")
    roles = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, permission FROM roles ORDER BY name")
            results = cur.fetchall()
    for result in results:
        roles.append({
            "id": result[0],
            "name": result[1],
            "permission": result[2],
        })
    logger.debug(f"Retrieved {len(roles)} roles from the database.")
    return roles

def create_role(name: str, permission: dict) -> dict:
    logger.debug(f"Creating role: {name}")
    error_message = "OK"
    role_id = None
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO roles (name, permission) VALUES (%s, %s) RETURNING id",
                    (name, json.dumps(permission)),
                )
                result = cur.fetchone()
                if result:
                    role_id = result[0]
            conn.commit()
    except Exception as e:
        error_message = f"Error creating role: {e}"
        logger.error(error_message)
    return {"role_id": role_id, "message": error_message}

def update_role(role_id: int, name: str, permission: dict) -> dict:
    logger.debug(f"Updating role ID: {role_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE roles SET name = %s, permission = %s WHERE id = %s",
                    (name, json.dumps(permission), role_id),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error updating role: {e}"
        logger.error(error_message)
    return {"role_id": role_id, "message": error_message}

def assign_role_to_member(member_id: int, role_id: int) -> dict:
    """Assign a role to a member, replacing any existing role (one role per member)."""
    logger.debug(f"Assigning role {role_id} to member {member_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Remove any existing role(s) for this member first
                cur.execute("DELETE FROM member_to_role WHERE member_id = %s", (member_id,))
                cur.execute(
                    "INSERT INTO member_to_role (member_id, role_id) VALUES (%s, %s)",
                    (member_id, role_id),
                )
            conn.commit()
    except Exception as e:
        error_message = f"Error assigning role: {e}"
        logger.error(error_message)
    return {"message": error_message}

def get_members_with_roles() -> list[dict]:
    """Get all members who have a role assigned, with their role info."""
    logger.debug("Getting all members with roles.")
    members = []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT   m.id AS member_id,
                         m.identity ->> 'first_name' AS first_name,
                         m.identity ->> 'last_name' AS last_name,
                         m.identity -> 'emails' -> 0 ->> 'email_address' AS primary_email,
                         r.id AS role_id,
                         r.name AS role_name
                FROM     member_to_role mtr
                JOIN     member m ON m.id = mtr.member_id
                JOIN     roles r ON r.id = mtr.role_id
                ORDER BY r.name, m.identity ->> 'last_name', m.identity ->> 'first_name';
                """
            )
            results = cur.fetchall()
    for result in results:
        members.append({
            "member_id": result[0],
            "first_name": result[1],
            "last_name": result[2],
            "primary_email": result[3],
            "role_id": result[4],
            "role_name": result[5],
        })
    logger.debug(f"Retrieved {len(members)} members with roles.")
    return members

def remove_role_from_member(member_id: int) -> dict:
    """Remove all role assignments for a member."""
    logger.debug(f"Removing role from member {member_id}")
    error_message = "OK"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM member_to_role WHERE member_id = %s", (member_id,))
            conn.commit()
    except Exception as e:
        error_message = f"Error removing role: {e}"
        logger.error(error_message)
    return {"message": error_message}
