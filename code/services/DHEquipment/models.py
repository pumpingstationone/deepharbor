from pydantic import BaseModel
from typing import Optional


###############################################################################
# OAuth2 Client Model (for service-to-service auth)
###############################################################################

class Client(BaseModel):
    client_name: str
    hashed_password: str
    description: str | None = None
    disabled: bool | None = None


###############################################################################
# Equipment Module Pydantic Models
# Adapted from PA1 — UUID fields changed to int for DH member references,
# equipment IDs changed to int.
###############################################################################

# ── Areas ──

class AreaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    metadata: dict = {}

# ── Equipment ──

class EquipmentCreate(BaseModel):
    area_id: Optional[int] = None
    common_name: Optional[str] = None
    make: str
    model: str
    serial_number: str
    schedulable: bool = False
    build_date: Optional[str] = None
    status: str = "active"
    electrical: dict = {}
    breaker: dict = {}
    attributes: dict = {}

class EquipmentUpdate(BaseModel):
    area_id: Optional[int] = None
    common_name: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    schedulable: Optional[bool] = None
    build_date: Optional[str] = None
    status: Optional[str] = None
    electrical: Optional[dict] = None
    breaker: Optional[dict] = None
    attributes: Optional[dict] = None
    attachments: Optional[list] = None
    version: int  # required for optimistic locking

# ── Repair Tickets ──

class TicketCreate(BaseModel):
    equipment_id: int
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    assigned_to: Optional[int] = None
    metadata: dict = {}

class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None
    metadata: Optional[dict] = None
    attachments: Optional[list] = None
    version: int  # required for optimistic locking

class WorkLogEntry(BaseModel):
    action: str
    notes: Optional[str] = None
    parts_used: list = []
    attachments: list = []

# ── Scheduling ──

class ScheduleCreate(BaseModel):
    equipment_id: int
    title: Optional[str] = None
    start_time: str   # ISO8601
    end_time: str
    notes: Optional[str] = None

# ── Authorization Sessions ──

class AuthSessionCreate(BaseModel):
    equipment_ids: list[int] = []
    title: str
    description: Optional[str] = None
    start_time: str
    end_time: str
    total_slots: int = 1

class AuthSessionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_slots: Optional[int] = None
    equipment_ids: Optional[list[int]] = None

# ── Equipment Groups ──

class EquipGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    area_id: Optional[int] = None
    equipment_ids: list[int] = []

class EquipGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    area_id: Optional[int] = None
    equipment_ids: Optional[list[int]] = None
    attachments: Optional[list] = None

# ── Maintenance ──

class MaintenanceScheduleCreate(BaseModel):
    title: str
    description: Optional[str] = None
    equipment_id: Optional[int] = None
    group_id: Optional[int] = None
    recurrence_type: str = "days"
    recurrence_interval: int = 30
    assigned_to: Optional[int] = None
    priority: str = "normal"
    estimated_minutes: Optional[int] = None
    checklist: list = []
    notify_roles: list = []

class MaintenanceScheduleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    equipment_id: Optional[int] = None
    group_id: Optional[int] = None
    recurrence_type: Optional[str] = None
    recurrence_interval: Optional[int] = None
    assigned_to: Optional[int] = None
    priority: Optional[str] = None
    estimated_minutes: Optional[int] = None
    checklist: Optional[list] = None
    notify_roles: Optional[list] = None
    is_active: Optional[bool] = None

class MaintenanceEventUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    assigned_to: Optional[int] = None
    checklist_state: Optional[list] = None
