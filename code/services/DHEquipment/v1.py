# *******************************************************************************
# DHEquipment Service — v1 API Endpoints
# All equipment management endpoints under /v1/equipment/
# *******************************************************************************

import io
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

import boto3
from botocore.client import Config
from fastapi import Depends, Request, HTTPException, UploadFile, File, Form

from fastapiapp import app
import auth
import db
import notifications
from dhs_logging import logger
from config import config as app_config

# S3/RustFS storage client
_STORAGE_ENDPOINT = app_config.get("storage", "endpoint_url", fallback="http://rustfs:9000")
_STORAGE_ACCESS_KEY = app_config.get("storage", "access_key", fallback="deepharbor")
_STORAGE_SECRET_KEY = app_config.get("storage", "secret_key", fallback="changeme")
_STORAGE_BUCKET = app_config.get("storage", "bucket", fallback="deepharbor-equipment")
_STORAGE_PUBLIC_URL = app_config.get("storage", "public_url", fallback="").rstrip("/")

_s3 = boto3.client(
    "s3",
    endpoint_url=_STORAGE_ENDPOINT,
    aws_access_key_id=_STORAGE_ACCESS_KEY,
    aws_secret_access_key=_STORAGE_SECRET_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)

_PUBLIC_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"],
        "Resource": [f"arn:aws:s3:::{_STORAGE_BUCKET}/*"],
    }],
})

_bucket_ready = False

def _ensure_bucket():
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        _s3.head_bucket(Bucket=_STORAGE_BUCKET)
    except Exception:
        try:
            _s3.create_bucket(Bucket=_STORAGE_BUCKET)
            logger.info(f"Created storage bucket: {_STORAGE_BUCKET}")
        except Exception as e:
            logger.warning(f"Could not create bucket {_STORAGE_BUCKET}: {e}")
            return
    try:
        _s3.put_bucket_policy(Bucket=_STORAGE_BUCKET, Policy=_PUBLIC_POLICY)
        logger.info(f"Applied public-read policy to bucket: {_STORAGE_BUCKET}")
    except Exception as e:
        logger.warning(f"Could not set bucket policy for {_STORAGE_BUCKET}: {e}")
    _bucket_ready = True
from models import (
    AreaCreate, EquipmentCreate, EquipmentUpdate,
    TicketCreate, TicketUpdate, WorkLogEntry,
    ScheduleCreate, AuthSessionCreate, AuthSessionUpdate,
    EquipGroupCreate, EquipGroupUpdate,
    MaintenanceScheduleCreate, MaintenanceScheduleUpdate, MaintenanceEventUpdate,
)

# Type alias for authenticated client dependency
AuthenticatedClient = Annotated[auth.Client, Depends(auth.get_current_active_client)]


###############################################################################
# Permission Checking
###############################################################################

def _get_member_context(request: Request) -> dict:
    """Extract member ID and permissions from request headers.
    These headers are set by the portal's Flask backend after SSO auth."""
    member_id = request.headers.get("X-Member-ID")
    perms_raw = request.headers.get("X-Member-Permissions", "{}")
    role_name = request.headers.get("X-Member-Role", "")
    try:
        permissions = json.loads(perms_raw)
    except (json.JSONDecodeError, ValueError):
        permissions = {}
    return {
        "member_id": int(member_id) if member_id else None,
        "permissions": permissions,
        "role": role_name,
    }


def _check_perm(request: Request, required: str, perm_type: str = "view"):
    """Check if the requesting member has the required permission.
    Raises 403 if permission is denied."""
    ctx = _get_member_context(request)
    perms = ctx["permissions"]
    perm_list = perms.get(perm_type, [])
    if "all" in perm_list or required in perm_list:
        return ctx
    # Also check if they have the permission in the other type
    # (having 'change' implies 'view')
    if perm_type == "view":
        change_list = perms.get("change", [])
        if "all" in change_list or required in change_list:
            return ctx
    raise HTTPException(403, f"Permission denied: requires {perm_type} on {required}")


def _require_view(request: Request, perm: str):
    return _check_perm(request, perm, "view")


def _require_change(request: Request, perm: str):
    return _check_perm(request, perm, "change")


###############################################################################
# Areas
###############################################################################

@app.get("/v1/equipment/areas")
async def list_areas(current_client: AuthenticatedClient):
    return db.list_areas()


@app.get("/v1/equipment/areas/{area_id}")
async def get_area(current_client: AuthenticatedClient, area_id: int):
    row = db.get_area(area_id)
    if not row:
        raise HTTPException(404, "Area not found")
    return row


@app.post("/v1/equipment/areas", status_code=201)
async def create_area(data: AreaCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.areas")
    try:
        row = db.create_area(data.name, data.description, data.metadata)
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(400, "Area name already exists")
        raise
    return row


@app.patch("/v1/equipment/areas/{area_id}")
async def update_area(area_id: int, data: dict, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.areas")
    allowed = {"name", "description", "metadata", "attachments"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    row = db.update_area(area_id, updates)
    if not row:
        raise HTTPException(404, "Area not found")
    return row


@app.delete("/v1/equipment/areas/{area_id}")
async def delete_area(area_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.areas")
    if not db.delete_area(area_id):
        raise HTTPException(404, "Area not found")
    return {"ok": True}


###############################################################################
# Equipment
###############################################################################

@app.get("/v1/equipment/items")
async def list_equipment(
    current_client: AuthenticatedClient,
    area_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    return db.list_equipment(area_id=area_id, status=status, search=search)


@app.get("/v1/equipment/items/{equipment_id}")
async def get_equipment(current_client: AuthenticatedClient, equipment_id: int):
    row = db.get_equipment(equipment_id)
    if not row:
        raise HTTPException(404, "Equipment not found")
    return row


@app.post("/v1/equipment/items", status_code=201)
async def create_equipment(data: EquipmentCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.items")
    try:
        row = db.create_equipment(data.model_dump())
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(400, "Serial number already exists")
        raise
    return row


@app.patch("/v1/equipment/items/{equipment_id}")
async def update_equipment(equipment_id: int, data: EquipmentUpdate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.items")
    # Optimistic locking check
    current_version = db.get_equipment_version(equipment_id)
    if current_version is None:
        raise HTTPException(404, "Equipment not found")
    if current_version != data.version:
        raise HTTPException(409, "Equipment was modified by another user. Please refresh and try again.")

    updates = {}
    for field in ("common_name", "make", "model", "serial_number", "build_date",
                  "status", "area_id", "schedulable", "electrical", "breaker",
                  "attributes", "attachments"):
        val = getattr(data, field, None)
        if val is not None:
            updates[field] = val
    if not updates:
        raise HTTPException(400, "No fields to update")

    old_equip = db.get_equipment(equipment_id)
    old_status = old_equip.get("status") if old_equip else None
    row = db.update_equipment(equipment_id, updates)
    if "status" in updates and row and row.get("status") != old_status:
        notifications.schedule_event("equipment_status_changed", {
            "id": equipment_id,
            "common_name": row.get("common_name"),
            "status": row.get("status"),
        })
    return row


@app.delete("/v1/equipment/items/{equipment_id}")
async def delete_equipment(equipment_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.items")
    if not db.delete_equipment(equipment_id):
        raise HTTPException(404, "Equipment not found")
    return {"ok": True}


###############################################################################
# Repair Tickets
###############################################################################

@app.get("/v1/equipment/tickets")
async def list_tickets(
    current_client: AuthenticatedClient,
    request: Request,
    equipment_id: Optional[int] = None,
    assigned_to: Optional[int] = None,
):
    # Support multiple status= and priority= query params
    qp = request.query_params
    statuses = [v for k, v in qp.multi_items() if k == "status"]
    priorities = [v for k, v in qp.multi_items() if k == "priority"]

    return db.list_tickets(
        equipment_id=equipment_id,
        assigned_to=assigned_to,
        statuses=statuses or None,
        priorities=priorities or None,
    )


@app.get("/v1/equipment/tickets/{ticket_id}")
async def get_ticket(current_client: AuthenticatedClient, ticket_id: int):
    row = db.get_ticket(ticket_id)
    if not row:
        raise HTTPException(404, "Ticket not found")
    return row


@app.post("/v1/equipment/tickets", status_code=201)
async def create_ticket(data: TicketCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.tickets")
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")
    row = db.create_ticket(data.model_dump(), opened_by=ctx["member_id"])
    notifications.schedule_event("ticket_opened", {
        "ticket_id": row.get("id"),
        "title": row.get("title"),
        "status": row.get("status"),
        "priority": row.get("priority"),
        "equipment_id": row.get("equipment_id"),
    })
    return row


@app.patch("/v1/equipment/tickets/{ticket_id}")
async def update_ticket(ticket_id: int, data: TicketUpdate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.tickets")
    current = db.get_ticket_version(ticket_id)
    if current is None:
        raise HTTPException(404, "Ticket not found")
    if current["version"] != data.version:
        raise HTTPException(409, "Ticket was modified by another user. Please refresh and try again.")

    old_status = current.get("status")
    updates = {}
    for field in ("title", "description", "status", "priority", "assigned_to", "metadata", "attachments"):
        val = getattr(data, field, None)
        if val is not None:
            updates[field] = val
    if not updates:
        raise HTTPException(400, "No fields to update")

    row = db.update_ticket(ticket_id, updates)
    new_status = row.get("status") if row else None
    if "status" in updates and new_status != old_status:
        event_name = "ticket_closed" if new_status == "closed" else "ticket_status_changed"
        notifications.schedule_event(event_name, {
            "ticket_id": row.get("id"),
            "title": row.get("title"),
            "status": new_status,
            "priority": row.get("priority"),
            "equipment_id": row.get("equipment_id"),
        })
    return row


@app.delete("/v1/equipment/tickets/{ticket_id}", status_code=204)
async def delete_ticket(ticket_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.tickets")
    if not db.delete_ticket(ticket_id):
        raise HTTPException(404, "Ticket not found")


@app.post("/v1/equipment/tickets/{ticket_id}/worklog")
async def add_work_log(ticket_id: int, entry: WorkLogEntry, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.tickets")
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "member_id": ctx["member_id"],
        "member_name": "",  # Will be populated by the portal
        "action": entry.action,
        "notes": entry.notes,
        "parts_used": entry.parts_used,
        "attachments": entry.attachments,
    }
    row = db.add_work_log_entry(ticket_id, log_entry)
    if not row:
        raise HTTPException(404, "Ticket not found")
    return row


###############################################################################
# Equipment Schedules
###############################################################################

@app.get("/v1/equipment/schedules")
async def list_schedules(
    current_client: AuthenticatedClient,
    equipment_id: Optional[int] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
):
    return db.list_schedules(equipment_id=equipment_id, from_time=from_time, to_time=to_time)


@app.post("/v1/equipment/schedules", status_code=201)
async def create_schedule(data: ScheduleCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.schedules")
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")

    # Validate duration
    try:
        start = datetime.fromisoformat(data.start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(data.end_time.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid datetime format")

    duration = (end - start).total_seconds()
    if duration < 900:
        raise HTTPException(400, "Minimum booking duration is 15 minutes")
    if duration > 86400:
        raise HTTPException(400, "Maximum booking duration is 24 hours")
    if end <= start:
        raise HTTPException(400, "End time must be after start time")

    row, error = db.create_schedule(data.model_dump(), member_id=ctx["member_id"])
    if error:
        status_code = 409 if "conflicts" in error.lower() else 400
        raise HTTPException(status_code, error)
    return row


@app.delete("/v1/equipment/schedules/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _get_member_context(request)
    owner = db.get_schedule_owner(schedule_id)
    if owner is None:
        raise HTTPException(404, "Schedule not found")
    # Only owner or someone with manage permission can delete
    if owner != ctx["member_id"]:
        _require_change(request, "equipment.schedules")
    if not db.delete_schedule(schedule_id):
        raise HTTPException(404, "Schedule not found")


###############################################################################
# Authorization Sessions
###############################################################################

@app.get("/v1/equipment/auth-sessions")
async def list_auth_sessions(
    current_client: AuthenticatedClient,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
):
    return db.list_auth_sessions(from_time=from_time, to_time=to_time)


@app.get("/v1/equipment/auth-sessions/{session_id}")
async def get_auth_session(current_client: AuthenticatedClient, session_id: int):
    row = db.get_auth_session(session_id)
    if not row:
        raise HTTPException(404, "Session not found")
    return row


@app.post("/v1/equipment/auth-sessions", status_code=201)
async def create_auth_session(data: AuthSessionCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.auth_sessions")
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")

    try:
        start = datetime.fromisoformat(data.start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(data.end_time.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid datetime format")
    if end <= start:
        raise HTTPException(400, "End time must be after start time")
    if data.total_slots < 1:
        raise HTTPException(400, "Must have at least 1 slot")

    row = db.create_auth_session(data.model_dump(), authorizer_id=ctx["member_id"])
    return row


@app.patch("/v1/equipment/auth-sessions/{session_id}")
async def update_auth_session(session_id: int, data: AuthSessionUpdate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.auth_sessions")
    updates = {}
    if data.title is not None:
        updates["title"] = data.title
    if data.description is not None:
        updates["description"] = data.description
    if data.total_slots is not None:
        updates["total_slots"] = data.total_slots
    if data.equipment_ids is not None:
        updates["equipment_ids"] = data.equipment_ids
    if data.start_time is not None:
        updates["start_time"] = datetime.fromisoformat(data.start_time.replace("Z", "+00:00"))
    if data.end_time is not None:
        updates["end_time"] = datetime.fromisoformat(data.end_time.replace("Z", "+00:00"))
    if not updates:
        raise HTTPException(400, "No fields to update")
    row = db.update_auth_session(session_id, updates)
    if not row:
        raise HTTPException(404, "Session not found")
    return row


@app.delete("/v1/equipment/auth-sessions/{session_id}", status_code=204)
async def delete_auth_session(session_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _get_member_context(request)
    authorizer = db.get_auth_session_authorizer(session_id)
    if authorizer is None:
        raise HTTPException(404, "Session not found")
    if authorizer != ctx["member_id"]:
        _require_change(request, "equipment.auth_sessions")
    if not db.delete_auth_session(session_id):
        raise HTTPException(404, "Session not found")


@app.post("/v1/equipment/auth-sessions/{session_id}/enroll", status_code=201)
async def enroll_in_session(session_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _get_member_context(request)
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")
    row, error = db.enroll_in_session(session_id, ctx["member_id"])
    if error:
        status_code = 409 if "full" in error.lower() or "already" in error.lower() else 404
        raise HTTPException(status_code, error)
    return row


@app.delete("/v1/equipment/auth-sessions/{session_id}/enroll", status_code=204)
async def unenroll_from_session(session_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _get_member_context(request)
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")
    if not db.unenroll_from_session(session_id, ctx["member_id"]):
        raise HTTPException(404, "Enrollment not found")


###############################################################################
# Equipment Groups
###############################################################################

@app.get("/v1/equipment/groups")
async def list_equipment_groups(current_client: AuthenticatedClient):
    return db.list_equipment_groups()


@app.post("/v1/equipment/groups", status_code=201)
async def create_equipment_group(data: EquipGroupCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.groups")
    return db.create_equipment_group(data.model_dump())


@app.patch("/v1/equipment/groups/{group_id}")
async def update_equipment_group(group_id: int, data: EquipGroupUpdate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.groups")
    row = db.update_equipment_group(group_id, data.model_dump(exclude_none=True))
    if not row:
        raise HTTPException(404, "Group not found")
    return row


@app.delete("/v1/equipment/groups/{group_id}", status_code=204)
async def delete_equipment_group(group_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.groups")
    if not db.delete_equipment_group(group_id):
        raise HTTPException(404, "Group not found")


###############################################################################
# Maintenance
###############################################################################

@app.get("/v1/equipment/maintenance/schedules")
async def list_maintenance_schedules(
    current_client: AuthenticatedClient,
    request: Request,
    equipment_id: Optional[int] = None,
    group_id: Optional[int] = None,
):
    _require_view(request, "equipment.maintenance")
    return db.list_maintenance_schedules(equipment_id=equipment_id, group_id=group_id)


@app.post("/v1/equipment/maintenance/schedules", status_code=201)
async def create_maintenance_schedule(data: MaintenanceScheduleCreate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.maintenance")
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")
    if not data.equipment_id and not data.group_id:
        raise HTTPException(400, "Either equipment_id or group_id is required")
    if data.recurrence_type not in ("days", "weeks", "months", "years"):
        raise HTTPException(400, "Invalid recurrence_type")
    if data.recurrence_interval < 1:
        raise HTTPException(400, "recurrence_interval must be >= 1")

    row = db.create_maintenance_schedule(data.model_dump(), created_by=ctx["member_id"])
    return row


@app.patch("/v1/equipment/maintenance/schedules/{schedule_id}")
async def update_maintenance_schedule(schedule_id: int, data: MaintenanceScheduleUpdate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.maintenance")
    row = db.update_maintenance_schedule(schedule_id, data.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(404, "Schedule not found or no fields to update")
    return row


@app.delete("/v1/equipment/maintenance/schedules/{schedule_id}", status_code=204)
async def delete_maintenance_schedule(schedule_id: int, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.maintenance")
    if not db.delete_maintenance_schedule(schedule_id):
        raise HTTPException(404, "Schedule not found")


@app.get("/v1/equipment/maintenance/events")
async def list_maintenance_events(
    current_client: AuthenticatedClient,
    request: Request,
    schedule_id: Optional[int] = None,
    equipment_id: Optional[int] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    _require_view(request, "equipment.maintenance")
    return db.list_maintenance_events(
        schedule_id=schedule_id, equipment_id=equipment_id,
        status=status, from_date=from_date, to_date=to_date,
    )


@app.patch("/v1/equipment/maintenance/events/{event_id}")
async def update_maintenance_event(event_id: int, data: MaintenanceEventUpdate, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.maintenance")
    if not ctx["member_id"]:
        raise HTTPException(400, "Member ID required")
    row = db.update_maintenance_event(event_id, data.model_dump(exclude_none=True), current_member_id=ctx["member_id"])
    if row is None:
        raise HTTPException(404, "Event not found or no fields to update")
    new_status = row.get("status")
    if new_status == "in_progress":
        notifications.schedule_event("maintenance_started", {
            "id": event_id,
            "equipment_id": row.get("equipment_id"),
            "status": new_status,
        })
    elif new_status == "completed":
        notifications.schedule_event("maintenance_completed", {
            "id": event_id,
            "equipment_id": row.get("equipment_id"),
            "status": new_status,
        })
    elif new_status == "overdue":
        notifications.schedule_event("maintenance_overdue", {
            "id": event_id,
            "equipment_id": row.get("equipment_id"),
            "status": new_status,
        })
    return row


###############################################################################
# Dashboard
###############################################################################

@app.get("/v1/equipment/dashboard/stats")
async def get_dashboard_stats(current_client: AuthenticatedClient):
    return db.get_dashboard_stats()


###############################################################################
# Config
###############################################################################

@app.get("/v1/equipment/config/{key}")
async def get_config(key: str, current_client: AuthenticatedClient):
    val = db.get_config(key)
    if val is None:
        return {}
    return val


@app.put("/v1/equipment/config/{key}")
async def set_config(key: str, request: Request, current_client: AuthenticatedClient):
    ctx = _require_change(request, "equipment.config")
    data = await request.json()
    result = db.set_config(key, data, updated_by=ctx.get("member_id"))
    return result


###############################################################################
# File Upload
###############################################################################

ALLOWED_ATTACHMENT_TYPES = {
    # Images
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml", "image/tiff",
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv",
    # Video
    "video/mp4", "video/quicktime", "video/x-msvideo", "video/webm", "video/mpeg",
}
MAX_UPLOAD_BYTES = 250 * 1024 * 1024  # 250 MB


@app.post("/v1/equipment/upload")
async def upload_file(
    request: Request,
    current_client: AuthenticatedClient,
    file: UploadFile = File(...),
    entity_type: str = Form(...),
    entity_id: str = Form("new"),
):
    _require_change(request, "equipment.items")
    _ensure_bucket()

    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(400, f"Unsupported file type: {content_type}")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 250 MB)")

    original_filename = file.filename or "upload"
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "bin"
    key = f"{entity_type}/{entity_id}/{uuid.uuid4().hex}.{ext}"

    try:
        _s3.put_object(
            Bucket=_STORAGE_BUCKET,
            Key=key,
            Body=io.BytesIO(data),
            ContentType=content_type,
        )
    except Exception as e:
        logger.error(f"Storage upload failed: {e}")
        raise HTTPException(500, "File storage failed")

    if _STORAGE_PUBLIC_URL:
        url = f"{_STORAGE_PUBLIC_URL}/{_STORAGE_BUCKET}/{key}"
    else:
        url = f"{_STORAGE_ENDPOINT}/{_STORAGE_BUCKET}/{key}"

    return {
        "url": url,
        "key": key,
        "filename": original_filename,
        "size": len(data),
        "content_type": content_type,
    }


@app.get("/v1/equipment/media/{key:path}")
async def get_media(key: str, current_client: AuthenticatedClient):
    from fastapi.responses import StreamingResponse
    import httpx
    url = f"{_STORAGE_ENDPOINT}/{_STORAGE_BUCKET}/{key}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
    if r.status_code != 200:
        raise HTTPException(r.status_code, "Media not found")
    content_type = r.headers.get("content-type", "application/octet-stream")
    return StreamingResponse(iter([r.content]), media_type=content_type)


@app.delete("/v1/equipment/media/{key:path}", status_code=204)
async def delete_media(key: str, request: Request, current_client: AuthenticatedClient):
    _require_change(request, "equipment.items")
    try:
        _s3.delete_object(Bucket=_STORAGE_BUCKET, Key=key)
    except Exception as e:
        logger.warning(f"Storage delete failed for key {key!r}: {e}")
        raise HTTPException(500, "File delete failed")
