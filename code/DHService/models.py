import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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


###############################################################################
# Signup-path identity validation
###############################################################################

class SignupIdentityIn(BaseModel):
    """Signup-path (INSERT) identity validation.

    Applied ONLY on the no-X-Member-ID branch of POST /v1/member/identity/ (the
    signup fallback). extra='allow' so the free-form identity blob passes through
    untouched; only active_directory_username is constrained — length/charset are
    enforced to match the signup form (1-16 chars, [A-Za-z0-9_-]), backstopping
    the client-side maxlength/pattern that a direct POST can bypass.

    Length/charset are checked only when a non-empty username is supplied;
    required-ness is deferred to #293 (empty/null AD usernames exist in prod).
    Not applied on the update path, so editing legacy members whose usernames
    already exceed 16 chars is unaffected.
    """
    model_config = ConfigDict(extra="allow")
    active_directory_username: str | None = None

    @field_validator("active_directory_username")
    @classmethod
    def _validate_ad_username(cls, v):
        if v is None or v.strip() == "":
            return v
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", v.strip()):
            raise ValueError(
                "active_directory_username must be 1-16 characters: "
                "letters, digits, underscore, or hyphen"
            )
        return v
