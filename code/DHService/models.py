from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

###############################################################################
# Internal auth model (used by auth.py + db.get_client_by_client_name)
###############################################################################

class Client(BaseModel):
    id: int | None = None
    client_name: str
    hashed_password: str
    description: str | None = None
    disabled: bool = False


###############################################################################
# Admin API: API client management
###############################################################################

# client_name shape: lowercase letters, digits, dash, underscore.
# Must start and end with [a-z0-9] (no leading/trailing dash or underscore).
# Length 3-64. See plan section "Validation rules for client_name".
ApiClientName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$",
    ),
]


class ApiClientOut(BaseModel):
    """Metadata-only client representation. Never contains client_secret."""
    id: int
    client_name: str
    client_description: str | None = None
    disabled: bool
    date_added: datetime | None = None
    created_by_member_id: int | None = None
    created_by_first_name: str | None = None
    created_by_last_name: str | None = None
    last_used_at: datetime | None = None
    rotated_at: datetime | None = None


class ApiClientCreateIn(BaseModel):
    client_name: ApiClientName
    client_description: str | None = Field(default=None, max_length=512)
    created_by_member_id: int | None = None


class ApiClientPatchIn(BaseModel):
    disabled: bool | None = None
    client_description: str | None = Field(default=None, max_length=512)


class ApiClientSecretOut(BaseModel):
    """One-time response for create + rotate. Plaintext returned ONCE."""
    id: int
    client_name: str
    plaintext_secret: str
