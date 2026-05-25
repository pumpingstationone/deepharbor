import json
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from datetime import datetime, timezone, date as date_type
from dateutil.relativedelta import relativedelta

from config import config
from dhs_logging import logger
from models import Client

###############################################################################
# Database Connection
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


def set_session_context(conn, member_id, role_name):
    """Set RLS session context for the current connection.
    Uses parameterized set_config() — safe against injection."""
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_user_id', %s, false)", (str(member_id or ''),))
        cur.execute("SELECT set_config('app.session_role', %s, false)", (str(role_name or ''),))


def clear_session_context(conn):
    """Reset session context after request."""
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_user_id', '', false)")
        cur.execute("SELECT set_config('app.session_role', '', false)")


###############################################################################
# Helpers
###############################################################################

def _dict_row(cur):
    """Fetch one row as a dict, or None."""
    row = cur.fetchone()
    if row is None:
        return None
    cols = [desc[0] for desc in cur.description]
    return _serialize_row(dict(zip(cols, row)))


def _dict_rows(cur):
    """Fetch all rows as a list of dicts."""
    rows = cur.fetchall()
    if not rows:
        return []
    cols = [desc[0] for desc in cur.description]
    return [_serialize_row(dict(zip(cols, row))) for row in rows]


def _serialize_row(d):
    """Serialize special types for JSON output."""
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, date_type):
            d[k] = v.isoformat()
        elif isinstance(v, str):
            # Auto-parse JSON strings from JSONB columns
            try:
                parsed = json.loads(v)
                if isinstance(parsed, (dict, list)):
                    d[k] = parsed
            except (json.JSONDecodeError, ValueError):
                pass
    return d


def parse_date(s):
    """Safely parse an ISO date string to a date, returning None on failure."""
    if not s:
        return None
    try:
        return date_type.fromisoformat(str(s).strip())
    except (ValueError, TypeError, AttributeError):
        return None


# SQL fragment to get a member's display name from the identity JSONB
MEMBER_NAME_SQL = "COALESCE(CONCAT({alias}.identity->>'first_name', ' ', {alias}.identity->>'last_name'), '')"


###############################################################################
# OAuth2
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
        disabled=False,
        hashed_password=client[1],
    )


###############################################################################
# Areas
###############################################################################

def list_areas():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.*, COUNT(e.id) as equipment_count
                FROM areas a
                LEFT JOIN equipment e ON e.area_id = a.id
                GROUP BY a.id ORDER BY a.name
            """)
            return _dict_rows(cur)


def get_area(area_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.*, COUNT(e.id) as equipment_count
                FROM areas a
                LEFT JOIN equipment e ON e.area_id = a.id
                WHERE a.id = %s
                GROUP BY a.id
            """, (area_id,))
            return _dict_row(cur)


def create_area(name: str, description: str, metadata: dict):
    # Ensure standard metadata keys
    meta = {"website": "", "host_name": "", "host_contact": "", "email": "", "discord": ""}
    meta.update(metadata)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO areas (name, description, metadata) VALUES (%s, %s, %s) RETURNING *",
                (name, description, json.dumps(meta))
            )
            row = _dict_row(cur)
        conn.commit()
    return row


def update_area(area_id: int, updates: dict):
    for col in ("metadata", "attachments"):
        if col in updates:
            updates[col] = json.dumps(updates[col])
    set_parts = []
    values = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        values.append(v)
    values.append(area_id)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE areas SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values
            )
            row = _dict_row(cur)
        conn.commit()
    return row


def delete_area(area_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM areas WHERE id = %s", (area_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


###############################################################################
# Equipment
###############################################################################

def list_equipment(area_id: int = None, status: str = None, search: str = None):
    conditions = ["1=1"]
    params = []

    if area_id:
        conditions.append("e.area_id = %s")
        params.append(area_id)
    if status:
        conditions.append("e.status = %s")
        params.append(status)
    if search:
        conditions.append(
            "(e.make ILIKE %s OR e.model ILIKE %s OR e.serial_number ILIKE %s OR e.common_name ILIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like, like])

    where = " AND ".join(conditions)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT e.*, a.name as area_name,
                       COUNT(t.id) as open_tickets
                FROM equipment e
                LEFT JOIN areas a ON a.id = e.area_id
                LEFT JOIN repair_tickets t ON t.equipment_id = e.id AND t.status != 'closed'
                WHERE {where}
                GROUP BY e.id, a.name
                ORDER BY e.make, e.model
            """, params)
            return _dict_rows(cur)


def get_equipment(equipment_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.*, a.name as area_name
                FROM equipment e
                LEFT JOIN areas a ON a.id = e.area_id
                WHERE e.id = %s
            """, (equipment_id,))
            return _dict_row(cur)


def create_equipment(data: dict):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO equipment
                    (area_id, common_name, make, model, serial_number, build_date,
                     status, schedulable, electrical, breaker, attributes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data.get("area_id"), data.get("common_name"),
                data["make"], data["model"], data["serial_number"],
                parse_date(data.get("build_date")),
                data.get("status", "active"), data.get("schedulable", False),
                json.dumps(data.get("electrical", {})),
                json.dumps(data.get("breaker", {})),
                json.dumps(data.get("attributes", {})),
            ))
            row = _dict_row(cur)
        conn.commit()
    return row


def get_equipment_version(equipment_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM equipment WHERE id = %s", (equipment_id,))
            row = cur.fetchone()
    return row[0] if row else None


def update_equipment(equipment_id: int, updates: dict):
    """Update equipment fields. Caller must check version for optimistic locking."""
    _DATE_COLS = {"build_date"}
    _JSON_COLS = {"electrical", "breaker", "attributes", "attachments"}

    set_parts = []
    values = []
    for k, v in updates.items():
        if k in _JSON_COLS:
            set_parts.append(f"{k} = %s")
            values.append(json.dumps(v))
        elif k in _DATE_COLS:
            set_parts.append(f"{k} = %s::date")
            values.append(v)
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)

    values.append(equipment_id)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE equipment SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values
            )
            row = _dict_row(cur)
        conn.commit()
    return row


def delete_equipment(equipment_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM equipment WHERE id = %s", (equipment_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


###############################################################################
# Repair Tickets
###############################################################################

def list_tickets(equipment_id: int = None, assigned_to: int = None,
                 statuses: list = None, priorities: list = None):
    conditions = ["1=1"]
    params = []

    if equipment_id:
        conditions.append("t.equipment_id = %s")
        params.append(equipment_id)
    if statuses:
        conditions.append("t.status IN %s")
        params.append(tuple(statuses))
    if assigned_to:
        conditions.append("t.assigned_to = %s")
        params.append(assigned_to)
    if priorities:
        conditions.append("t.priority IN %s")
        params.append(tuple(priorities))

    where = " AND ".join(conditions)

    opener_name = MEMBER_NAME_SQL.format(alias="opener")
    assignee_name = MEMBER_NAME_SQL.format(alias="assignee")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT t.id, t.equipment_id, t.ticket_number, t.opened_by, t.assigned_to,
                       t.status, t.priority, t.title, t.description, t.work_log,
                       t.parts_used, t.metadata, t.opened_at, t.closed_at, t.category, t.version,
                       COALESCE(e.common_name, e.make || ' ' || e.model) as equipment_name,
                       e.serial_number,
                       a.name as area_name,
                       {opener_name} as opened_by_name,
                       {assignee_name} as assigned_to_name
                FROM repair_tickets t
                LEFT JOIN equipment e ON e.id = t.equipment_id
                LEFT JOIN areas a ON a.id = e.area_id
                LEFT JOIN member opener ON opener.id = t.opened_by
                LEFT JOIN member assignee ON assignee.id = t.assigned_to
                WHERE {where}
                ORDER BY
                  CASE t.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
                  t.opened_at DESC
            """, params)
            return _dict_rows(cur)


def get_ticket(ticket_id: int):
    opener_name = MEMBER_NAME_SQL.format(alias="opener")
    assignee_name = MEMBER_NAME_SQL.format(alias="assignee")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT t.id, t.equipment_id, t.ticket_number, t.opened_by, t.assigned_to,
                       t.status, t.priority, t.title, t.description, t.work_log,
                       t.parts_used, t.metadata, t.opened_at, t.closed_at, t.category, t.version,
                       COALESCE(e.common_name, e.make || ' ' || e.model) as equipment_name,
                       e.serial_number,
                       a.name as area_name,
                       {opener_name} as opened_by_name,
                       {assignee_name} as assigned_to_name
                FROM repair_tickets t
                LEFT JOIN equipment e ON e.id = t.equipment_id
                LEFT JOIN areas a ON a.id = e.area_id
                LEFT JOIN member opener ON opener.id = t.opened_by
                LEFT JOIN member assignee ON assignee.id = t.assigned_to
                WHERE t.id = %s
            """, (ticket_id,))
            return _dict_row(cur)


def create_ticket(data: dict, opened_by: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get next ticket number
            cur.execute("SELECT next_ticket_number()")
            ticket_number = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO repair_tickets
                    (equipment_id, ticket_number, opened_by, assigned_to,
                     title, description, priority, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data["equipment_id"], ticket_number, opened_by,
                data.get("assigned_to"), data["title"],
                data.get("description"), data.get("priority", "normal"),
                json.dumps(data.get("metadata", {}))
            ))
            row = _dict_row(cur)

            # Set equipment to under_repair if currently active
            cur.execute(
                "UPDATE equipment SET status='under_repair' WHERE id = %s AND status = 'active'",
                (data["equipment_id"],)
            )
        conn.commit()
    return row


def get_ticket_version(ticket_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version, status, equipment_id FROM repair_tickets WHERE id = %s", (ticket_id,))
            row = cur.fetchone()
    if row is None:
        return None
    return {"version": row[0], "status": row[1], "equipment_id": row[2]}


def update_ticket(ticket_id: int, updates: dict):
    _JSON_COLS = {"metadata", "attachments"}

    if updates.get("status") == "closed":
        updates["closed_at"] = datetime.now(timezone.utc).isoformat()

    set_parts = []
    values = []
    for k, v in updates.items():
        if k in _JSON_COLS:
            set_parts.append(f"{k} = %s")
            values.append(json.dumps(v))
        else:
            set_parts.append(f"{k} = %s")
            values.append(v)

    values.append(ticket_id)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE repair_tickets SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values
            )
            row = _dict_row(cur)

            # If closing, check if equipment can be set back to active
            if updates.get("status") == "closed" and row:
                cur.execute(
                    "SELECT COUNT(*) FROM repair_tickets WHERE equipment_id = %s AND status != 'closed'",
                    (row["equipment_id"],)
                )
                open_count = cur.fetchone()[0]
                if open_count == 0:
                    cur.execute(
                        "UPDATE equipment SET status='active' WHERE id = %s AND status = 'under_repair'",
                        (row["equipment_id"],)
                    )
        conn.commit()
    return row


def delete_ticket(ticket_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get equipment_id before deleting
            cur.execute("SELECT equipment_id FROM repair_tickets WHERE id = %s", (ticket_id,))
            ticket = cur.fetchone()
            if not ticket:
                return False
            equipment_id = ticket[0]

            cur.execute("DELETE FROM repair_tickets WHERE id = %s", (ticket_id,))
            if cur.rowcount == 0:
                return False

            # Revert equipment status if no remaining open tickets
            if equipment_id:
                cur.execute(
                    "SELECT COUNT(*) FROM repair_tickets WHERE equipment_id = %s AND status != 'closed'",
                    (equipment_id,)
                )
                open_count = cur.fetchone()[0]
                if open_count == 0:
                    cur.execute(
                        "UPDATE equipment SET status='active' WHERE id = %s AND status = 'under_repair'",
                        (equipment_id,)
                    )
        conn.commit()
    return True


def add_work_log_entry(ticket_id: int, entry: dict):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE repair_tickets
                SET work_log = work_log || %s::jsonb,
                    status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END
                WHERE id = %s
                RETURNING *
            """, (json.dumps([entry]), ticket_id))
            row = _dict_row(cur)
        conn.commit()
    return row


###############################################################################
# Equipment Schedules
###############################################################################

def list_schedules(equipment_id: int = None, from_time: str = None, to_time: str = None):
    conditions = ["1=1"]
    params = []

    if equipment_id:
        conditions.append("s.equipment_id = %s")
        params.append(equipment_id)
    if from_time:
        conditions.append("s.end_time > %s")
        params.append(from_time)
    if to_time:
        conditions.append("s.start_time < %s")
        params.append(to_time)

    where = " AND ".join(conditions)
    member_name = MEMBER_NAME_SQL.format(alias="m")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.id, s.equipment_id, s.member_id, s.title, s.start_time, s.end_time,
                       s.notes, s.created_at,
                       COALESCE(e.common_name, e.make || ' ' || e.model) as equipment_name,
                       {member_name} as member_name
                FROM equipment_schedules s
                LEFT JOIN equipment e ON e.id = s.equipment_id
                LEFT JOIN member m ON m.id = s.member_id
                WHERE {where}
                ORDER BY s.start_time
            """, params)
            return _dict_rows(cur)


def create_schedule(data: dict, member_id: int):
    """Create a schedule booking. Double-booking is checked at application layer."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Verify equipment is schedulable
            cur.execute("SELECT schedulable FROM equipment WHERE id = %s", (data["equipment_id"],))
            equip = cur.fetchone()
            if not equip:
                return None, "Equipment not found"
            if not equip[0]:
                return None, "This equipment is not enabled for scheduling"

            # Check for overlapping bookings (application-layer double-booking prevention)
            cur.execute("""
                SELECT COUNT(*) FROM equipment_schedules
                WHERE equipment_id = %s
                  AND start_time < %s AND end_time > %s
            """, (data["equipment_id"], data["end_time"], data["start_time"]))
            if cur.fetchone()[0] > 0:
                return None, "This time slot conflicts with an existing booking"

            cur.execute("""
                INSERT INTO equipment_schedules (equipment_id, member_id, title, start_time, end_time, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data["equipment_id"], member_id,
                data.get("title"), data["start_time"], data["end_time"],
                data.get("notes")
            ))
            row = _dict_row(cur)
        conn.commit()
    return row, None


def get_schedule_owner(schedule_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT member_id FROM equipment_schedules WHERE id = %s", (schedule_id,))
            row = cur.fetchone()
    return row[0] if row else None


def delete_schedule(schedule_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM equipment_schedules WHERE id = %s", (schedule_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


###############################################################################
# Authorization Sessions
###############################################################################

def list_auth_sessions(from_time: str = None, to_time: str = None):
    conditions = ["1=1"]
    params = []

    if from_time:
        conditions.append("a.end_time > %s")
        params.append(from_time)
    if to_time:
        conditions.append("a.start_time < %s")
        params.append(to_time)

    where = " AND ".join(conditions)
    authorizer_name = MEMBER_NAME_SQL.format(alias="m")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.id, a.equipment_ids, a.authorizer_id, a.title, a.description,
                       a.start_time, a.end_time, a.total_slots, a.created_at,
                       {authorizer_name} as authorizer_name,
                       COUNT(en.id) as enrolled_count,
                       COALESCE(
                         json_agg(json_build_object(
                           'member_id', en.member_id, 'enrolled_at', en.enrolled_at
                         ) ORDER BY en.enrolled_at) FILTER (WHERE en.id IS NOT NULL),
                         '[]'::json
                       ) as enrollments
                FROM equip_auth_sessions a
                LEFT JOIN member m ON m.id = a.authorizer_id
                LEFT JOIN equip_auth_enrollments en ON en.session_id = a.id
                WHERE {where}
                GROUP BY a.id, m.id
                ORDER BY a.start_time
            """, params)
            return _dict_rows(cur)


def get_auth_session(session_id: int):
    authorizer_name = MEMBER_NAME_SQL.format(alias="m")
    enrollee_name = MEMBER_NAME_SQL.format(alias="em")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.id, a.equipment_ids, a.authorizer_id, a.title, a.description,
                       a.start_time, a.end_time, a.total_slots, a.created_at,
                       {authorizer_name} as authorizer_name,
                       COUNT(en.id) as enrolled_count
                FROM equip_auth_sessions a
                LEFT JOIN member m ON m.id = a.authorizer_id
                LEFT JOIN equip_auth_enrollments en ON en.session_id = a.id
                WHERE a.id = %s
                GROUP BY a.id, m.id
            """, (session_id,))
            row = _dict_row(cur)
            if not row:
                return None

            cur.execute(f"""
                SELECT en.id, en.member_id, en.enrolled_at,
                       {enrollee_name} as member_name
                FROM equip_auth_enrollments en
                JOIN member em ON em.id = en.member_id
                WHERE en.session_id = %s
                ORDER BY en.enrolled_at
            """, (session_id,))
            row["enrollments"] = _dict_rows(cur)
    return row


def create_auth_session(data: dict, authorizer_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO equip_auth_sessions
                    (equipment_ids, authorizer_id, title, description, start_time, end_time, total_slots)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data.get("equipment_ids", []), authorizer_id,
                data["title"], data.get("description"),
                data["start_time"], data["end_time"],
                data.get("total_slots", 1)
            ))
            row = _dict_row(cur)
        conn.commit()
    return row


def update_auth_session(session_id: int, updates: dict):
    set_parts = []
    values = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        values.append(v)
    values.append(session_id)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE equip_auth_sessions SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values
            )
            row = _dict_row(cur)
        conn.commit()
    return row


def get_auth_session_authorizer(session_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT authorizer_id FROM equip_auth_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
    return row[0] if row else None


def delete_auth_session(session_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM equip_auth_sessions WHERE id = %s", (session_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def enroll_in_session(session_id: int, member_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check capacity
            cur.execute("""
                SELECT a.total_slots, COUNT(en.id) as enrolled_count
                FROM equip_auth_sessions a
                LEFT JOIN equip_auth_enrollments en ON en.session_id = a.id
                WHERE a.id = %s
                GROUP BY a.id
            """, (session_id,))
            session = cur.fetchone()
            if not session:
                return None, "Session not found"
            if session[1] >= session[0]:
                return None, "This session is full"

            try:
                cur.execute(
                    "INSERT INTO equip_auth_enrollments (session_id, member_id) VALUES (%s, %s) RETURNING *",
                    (session_id, member_id)
                )
                cols = [desc[0] for desc in cur.description]
                row = _serialize_row(dict(zip(cols, cur.fetchone())))
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                return None, "Already enrolled in this session"
        conn.commit()
    return row, None


def unenroll_from_session(session_id: int, member_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM equip_auth_enrollments WHERE session_id = %s AND member_id = %s",
                (session_id, member_id)
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


###############################################################################
# Equipment Groups
###############################################################################

def list_equipment_groups():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT g.id, g.name, g.description, g.area_id, g.attachments, g.created_at,
                       a.name as area_name,
                       COALESCE(
                         json_agg(json_build_object(
                           'id', e.id,
                           'common_name', e.common_name,
                           'make', e.make, 'model', e.model,
                           'status', e.status
                         ) ORDER BY gm.sort_order) FILTER (WHERE e.id IS NOT NULL),
                         '[]'::json
                       ) as equipment
                FROM equipment_groups g
                LEFT JOIN areas a ON a.id = g.area_id
                LEFT JOIN equipment_group_members gm ON gm.group_id = g.id
                LEFT JOIN equipment e ON e.id = gm.equipment_id
                GROUP BY g.id, a.id
                ORDER BY g.name
            """)
            return _dict_rows(cur)


def create_equipment_group(data: dict):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO equipment_groups (name, description, area_id) VALUES (%s, %s, %s) RETURNING *",
                (data["name"], data.get("description"), data.get("area_id"))
            )
            row = _dict_row(cur)
            for i, eid in enumerate(data.get("equipment_ids", [])):
                cur.execute(
                    "INSERT INTO equipment_group_members (group_id, equipment_id, sort_order) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (row["id"], eid, i)
                )
        conn.commit()
    return row


def update_equipment_group(group_id: int, data: dict):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            updates = {}
            if data.get("name") is not None:
                updates["name"] = data["name"]
            if data.get("description") is not None:
                updates["description"] = data["description"]
            if data.get("area_id") is not None:
                updates["area_id"] = data["area_id"]
            if "attachments" in data:
                updates["attachments"] = json.dumps(data["attachments"])

            if updates:
                set_parts = [f"{k} = %s" for k in updates]
                values = list(updates.values()) + [group_id]
                cur.execute(
                    f"UPDATE equipment_groups SET {', '.join(set_parts)} WHERE id = %s",
                    values
                )

            if data.get("equipment_ids") is not None:
                cur.execute("DELETE FROM equipment_group_members WHERE group_id = %s", (group_id,))
                for i, eid in enumerate(data["equipment_ids"]):
                    cur.execute(
                        "INSERT INTO equipment_group_members (group_id, equipment_id, sort_order) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (group_id, eid, i)
                    )
        conn.commit()

    return get_equipment_group_by_id(group_id)


def get_equipment_group_by_id(group_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT g.id, g.name, g.description, g.area_id, g.attachments, g.created_at,
                       COALESCE(json_agg(json_build_object(
                         'id', e.id, 'common_name', e.common_name,
                         'make', e.make, 'model', e.model, 'status', e.status
                       ) ORDER BY gm.sort_order) FILTER (WHERE e.id IS NOT NULL), '[]'::json) as equipment
                FROM equipment_groups g
                LEFT JOIN equipment_group_members gm ON gm.group_id = g.id
                LEFT JOIN equipment e ON e.id = gm.equipment_id
                WHERE g.id = %s GROUP BY g.id
            """, (group_id,))
            return _dict_row(cur)


def delete_equipment_group(group_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM equipment_groups WHERE id = %s", (group_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


###############################################################################
# Maintenance
###############################################################################

def _next_due_date(from_date, rec_type: str, rec_interval: int):
    """Calculate next due date from a given date based on recurrence."""
    base = from_date if isinstance(from_date, datetime) else datetime.fromisoformat(
        str(from_date).replace("Z", "+00:00")
    )
    if rec_type == "days":
        return base + relativedelta(days=rec_interval)
    elif rec_type == "weeks":
        return base + relativedelta(weeks=rec_interval)
    elif rec_type == "months":
        return base + relativedelta(months=rec_interval)
    elif rec_type == "years":
        return base + relativedelta(years=rec_interval)
    return base + relativedelta(days=rec_interval)


def _create_next_event(cur, schedule: dict, from_date=None):
    """Create the next pending maintenance event for a schedule."""
    cur.execute(
        "SELECT COUNT(*) FROM maintenance_events WHERE schedule_id = %s AND status IN ('pending', 'in_progress')",
        (schedule["id"],)
    )
    if cur.fetchone()[0] > 0:
        return None

    if from_date:
        due = _next_due_date(from_date, schedule["recurrence_type"], schedule["recurrence_interval"])
    else:
        due = datetime.now(timezone.utc) + relativedelta(days=1)

    equip_id = schedule.get("equipment_id")

    cur.execute("""
        INSERT INTO maintenance_events (schedule_id, equipment_id, due_date, assigned_to, checklist_state)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
    """, (
        schedule["id"], equip_id, due,
        schedule.get("assigned_to"),
        json.dumps(schedule.get("checklist") or [])
    ))
    cols = [desc[0] for desc in cur.description]
    return _serialize_row(dict(zip(cols, cur.fetchone())))


def list_maintenance_schedules(equipment_id: int = None, group_id: int = None):
    conditions = ["1=1"]
    params = []

    if equipment_id:
        conditions.append("ms.equipment_id = %s")
        params.append(equipment_id)
    if group_id:
        conditions.append("ms.group_id = %s")
        params.append(group_id)

    where = " AND ".join(conditions)
    assigned_name = MEMBER_NAME_SQL.format(alias="u")
    creator_name = MEMBER_NAME_SQL.format(alias="c")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT ms.*,
                       e.common_name as equipment_name, e.make as equipment_make, e.model as equipment_model,
                       eg.name as group_name,
                       {assigned_name} as assigned_name,
                       {creator_name} as creator_name
                FROM maintenance_schedules ms
                LEFT JOIN equipment e ON e.id = ms.equipment_id
                LEFT JOIN equipment_groups eg ON eg.id = ms.group_id
                LEFT JOIN member u ON u.id = ms.assigned_to
                LEFT JOIN member c ON c.id = ms.created_by
                WHERE {where}
                ORDER BY ms.created_at DESC
            """, params)
            return _dict_rows(cur)


def create_maintenance_schedule(data: dict, created_by: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO maintenance_schedules
                    (title, description, equipment_id, group_id, recurrence_type, recurrence_interval,
                     assigned_to, created_by, priority, estimated_minutes, checklist, notify_roles)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                data["title"], data.get("description"),
                data.get("equipment_id"), data.get("group_id"),
                data.get("recurrence_type", "days"), data.get("recurrence_interval", 30),
                data.get("assigned_to"), created_by,
                data.get("priority", "normal"), data.get("estimated_minutes"),
                json.dumps(data.get("checklist", [])),
                data.get("notify_roles", [])
            ))
            row = _dict_row(cur)
            # Create the first pending event
            schedule = dict(row)
            # Re-parse checklist since _dict_row may have already parsed it
            if isinstance(schedule.get("checklist"), str):
                schedule["checklist"] = json.loads(schedule["checklist"])
            _create_next_event(cur, schedule)
        conn.commit()
    return row


def update_maintenance_schedule(schedule_id: int, data: dict):
    updates = {}
    for field in ("title", "description", "equipment_id", "group_id", "recurrence_type",
                  "recurrence_interval", "assigned_to", "priority", "estimated_minutes", "is_active"):
        val = data.get(field)
        if val is not None:
            updates[field] = val
    if "checklist" in data and data["checklist"] is not None:
        updates["checklist"] = json.dumps(data["checklist"])
    if "notify_roles" in data and data["notify_roles"] is not None:
        updates["notify_roles"] = data["notify_roles"]
    if not updates:
        return None

    set_parts = [f"{k} = %s" for k in updates]
    values = list(updates.values()) + [schedule_id]
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE maintenance_schedules SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values
            )
            row = _dict_row(cur)
        conn.commit()
    return row


def delete_maintenance_schedule(schedule_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM maintenance_schedules WHERE id = %s", (schedule_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def list_maintenance_events(schedule_id: int = None, equipment_id: int = None,
                            status: str = None, from_date: str = None, to_date: str = None):
    conditions = ["1=1"]
    params = []

    if schedule_id:
        conditions.append("me.schedule_id = %s")
        params.append(schedule_id)
    if equipment_id:
        conditions.append("(me.equipment_id = %s OR ms.equipment_id = %s)")
        params.extend([equipment_id, equipment_id])
    if status:
        conditions.append("me.status = %s")
        params.append(status)
    if from_date:
        conditions.append("me.due_date >= %s::timestamptz")
        params.append(from_date)
    if to_date:
        conditions.append("me.due_date <= %s::timestamptz")
        params.append(to_date)

    where = " AND ".join(conditions)
    assigned_name = MEMBER_NAME_SQL.format(alias="u")
    completed_name = MEMBER_NAME_SQL.format(alias="cb")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT me.*, ms.title, ms.description as schedule_description, ms.priority,
                       ms.estimated_minutes, ms.recurrence_type, ms.recurrence_interval,
                       ms.group_id, ms.equipment_id as schedule_equipment_id,
                       e.common_name as equipment_name, e.make as equipment_make, e.model as equipment_model,
                       eg.name as group_name,
                       {assigned_name} as assigned_name,
                       {completed_name} as completed_by_name,
                       rt.ticket_number
                FROM maintenance_events me
                JOIN maintenance_schedules ms ON ms.id = me.schedule_id
                LEFT JOIN equipment e ON e.id = COALESCE(me.equipment_id, ms.equipment_id)
                LEFT JOIN equipment_groups eg ON eg.id = ms.group_id
                LEFT JOIN member u ON u.id = me.assigned_to
                LEFT JOIN member cb ON cb.id = me.completed_by
                LEFT JOIN repair_tickets rt ON rt.id = me.ticket_id
                WHERE {where}
                ORDER BY me.due_date ASC
            """, params)
            return _dict_rows(cur)


def update_maintenance_event(event_id: int, data: dict, current_member_id: int):
    """Update a maintenance event. Handles auto-ticket creation on start,
    auto-ticket closing on completion, and next-event generation."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Get existing event + schedule info
            cur.execute("""
                SELECT me.*, ms.recurrence_type, ms.recurrence_interval, ms.is_active as schedule_active,
                       ms.id as sid, ms.title as sched_title, ms.description as sched_desc,
                       ms.priority as sched_priority, ms.assigned_to as sched_assigned,
                       ms.equipment_id as sched_equip_id, ms.checklist
                FROM maintenance_events me
                JOIN maintenance_schedules ms ON ms.id = me.schedule_id
                WHERE me.id = %s
            """, (event_id,))
            existing_row = cur.fetchone()
            if not existing_row:
                return None
            cols = [desc[0] for desc in cur.description]
            existing = dict(zip(cols, existing_row))

            updates = {}
            if data.get("status") is not None:
                updates["status"] = data["status"]
            if data.get("notes") is not None:
                updates["notes"] = data["notes"]
            if data.get("assigned_to") is not None:
                updates["assigned_to"] = data["assigned_to"]
            if data.get("checklist_state") is not None:
                updates["checklist_state"] = json.dumps(data["checklist_state"])

            # On START: auto-create a linked maintenance ticket
            if data.get("status") == "in_progress" and not existing.get("ticket_id"):
                equip_id = existing.get("equipment_id") or existing.get("sched_equip_id")
                if equip_id:
                    cur.execute("SELECT next_ticket_number()")
                    ticket_number = cur.fetchone()[0]
                    cur.execute("""
                        INSERT INTO repair_tickets
                            (equipment_id, ticket_number, opened_by, assigned_to, title, description,
                             priority, status, category, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'in_progress', 'maintenance', %s)
                        RETURNING id
                    """, (
                        equip_id, ticket_number, current_member_id,
                        existing.get("assigned_to") or existing.get("sched_assigned"),
                        f"[Maintenance] {existing.get('sched_title', 'Scheduled Maintenance')}",
                        existing.get("sched_desc") or f"Auto-created from maintenance schedule. Event ID: {event_id}",
                        existing.get("sched_priority", "normal"),
                        json.dumps({"maintenance_event_id": event_id, "auto_created": True})
                    ))
                    ticket_row = cur.fetchone()
                    if ticket_row:
                        updates["ticket_id"] = ticket_row[0]
                        cur.execute(
                            "UPDATE equipment SET status='under_repair' WHERE id = %s AND status = 'active'",
                            (equip_id,)
                        )

            # Handle completion
            if data.get("status") in ("completed", "skipped"):
                updates["completed_by"] = current_member_id
                updates["completed_at"] = datetime.now(timezone.utc).isoformat()

            if not updates:
                return None

            set_parts = [f"{k} = %s" for k in updates]
            values = list(updates.values()) + [event_id]
            cur.execute(
                f"UPDATE maintenance_events SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                values
            )
            row = _dict_row(cur)

            # On COMPLETION: auto-close the linked ticket
            if data.get("status") == "completed":
                ticket_id = (row or {}).get("ticket_id") or existing.get("ticket_id")
                if ticket_id:
                    cur.execute(
                        "UPDATE repair_tickets SET status='closed', closed_at=NOW() WHERE id = %s AND status != 'closed'",
                        (ticket_id,)
                    )
                    equip_id = existing.get("equipment_id") or existing.get("sched_equip_id")
                    if equip_id:
                        cur.execute(
                            "SELECT COUNT(*) FROM repair_tickets WHERE equipment_id = %s AND status != 'closed'",
                            (equip_id,)
                        )
                        if cur.fetchone()[0] == 0:
                            cur.execute(
                                "UPDATE equipment SET status='active' WHERE id = %s AND status = 'under_repair'",
                                (equip_id,)
                            )

            # On completion/skip: create the NEXT event
            if data.get("status") in ("completed", "skipped") and existing.get("schedule_active"):
                cur.execute("SELECT * FROM maintenance_schedules WHERE id = %s", (existing["sid"],))
                sched_row = cur.fetchone()
                if sched_row:
                    sched_cols = [desc[0] for desc in cur.description]
                    sched = _serialize_row(dict(zip(sched_cols, sched_row)))
                    _create_next_event(cur, sched, from_date=datetime.now(timezone.utc))

        conn.commit()
    return row


###############################################################################
# Dashboard Stats
###############################################################################

def get_dashboard_stats():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                  (SELECT COUNT(*) FROM equipment) as total_equipment,
                  (SELECT COUNT(*) FROM equipment WHERE status = 'active') as active_equipment,
                  (SELECT COUNT(*) FROM equipment WHERE status = 'under_repair') as under_repair,
                  (SELECT COUNT(*) FROM repair_tickets WHERE status != 'closed') as open_tickets,
                  (SELECT COUNT(*) FROM repair_tickets WHERE status != 'closed' AND priority IN ('high','critical')) as critical_tickets,
                  (SELECT COUNT(*) FROM areas) as total_areas
            """)
            stats = _dict_row(cur)

            cur.execute("""
                SELECT a.name, COUNT(e.id) as count,
                       SUM(CASE WHEN e.status = 'under_repair' THEN 1 ELSE 0 END) as in_repair
                FROM areas a
                LEFT JOIN equipment e ON e.area_id = a.id
                GROUP BY a.id, a.name ORDER BY a.name
            """)
            area_breakdown = _dict_rows(cur)
    return {"summary": stats, "areas": area_breakdown}


###############################################################################
# Equipment Config
###############################################################################

def get_config(key: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM equipment_config WHERE key = %s", (key,))
            row = cur.fetchone()
    if not row:
        return None
    val = row[0]
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            pass
    return val


def get_all_config():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM equipment_config")
            rows = cur.fetchall()
    result = {}
    for key, value in rows:
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                result[key] = value
        else:
            result[key] = value
    return result


def set_config(key: str, value, updated_by: int = None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO equipment_config (key, value, updated_at, updated_by)
                VALUES (%s, %s, NOW(), %s)
                ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW(), updated_by = %s
            """, (key, json.dumps(value), updated_by, json.dumps(value), updated_by))
        conn.commit()
    return {"key": key, "value": value}


###############################################################################
# Notification Config (stored in equipment_config)
###############################################################################

def load_notification_config():
    return get_config("notifications") or {}


def save_notification_config(config_data: dict, updated_by: int = None):
    return set_config("notifications", config_data, updated_by)
