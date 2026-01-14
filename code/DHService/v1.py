# *******************************************************************************
# This file contains all the v1 services
# *******************************************************************************

from typing import Annotated
from fastapi import Depends, Request, Header

from fastapiapp import app
import auth
from dhs_logging import logger
import db

# Type alias for authenticated client dependency
AuthenticatedClient = Annotated[auth.Client, Depends(auth.get_current_active_client)]

###############################################################################
# Helper functions
###############################################################################

def _create_member_getter(field_name: str, db_func, wrap_key: str = None):
    """Factory function to create member getter endpoints."""
    async def getter(
        current_user: AuthenticatedClient,
        member_id: str,
    ):
        result = db_func(member_id)
        return {wrap_key: result} if wrap_key else result
    return getter

async def _get_member_id_and_json(request: Request) -> tuple[str, dict]:
    """Extract member ID from header and parse JSON body."""
    member_id = request.headers.get("X-Member-ID")
    data = await request.json()
    return member_id, data

###############################################################################
# Member GET endpoints
###############################################################################

@app.get("/v1/member/id")
async def get_member_id_from_email(current_user: AuthenticatedClient, email_address: str):
    """Get member ID from email address."""
    return {"member_id": db.get_member_id_from_email(email_address)}

@app.get("/v1/member/identity/")
async def get_member_identity(current_user: AuthenticatedClient, member_id: str):
    """Get member identity information."""
    return db.get_member_identity(member_id)

@app.get("/v1/member/search/")
async def search_members(current_user: AuthenticatedClient, query: str):
    """ Search for members based on a query string.
        Note that this is specifically searching both identity
        and access information, not _everything_ about a member.
        There is a separate database function for that (search_members),
        but it is not currently exposed via an endpoint because
        it finds names in too many other fields (e.g., the "notes"
        field).
    """
    return db.search_members_by_identity_and_access(query)

@app.get("/v1/member/username_check/")
async def check_member_username(current_user: AuthenticatedClient, username: str):
    """Check if a username is available."""
    return {"available": db.is_username_available(username)}

@app.get("/v1/member/connections/")
async def get_member_connections(current_user: AuthenticatedClient, member_id: str):
    """Get member connections."""
    return db.get_member_connections(member_id)

@app.get("/v1/member/status/")
async def get_member_status(current_user: AuthenticatedClient, member_id: str):
    """Get member status."""
    return db.get_member_status(member_id)

@app.get("/v1/member/forms/")
async def get_member_forms(current_user: AuthenticatedClient, member_id: str):
    """Get member forms data."""
    return db.get_member_forms(member_id)

@app.get("/v1/member/access/")
async def get_member_access(current_user: AuthenticatedClient, member_id: str):
    """Get member access data."""
    return db.get_member_access(member_id)

@app.get("/v1/member/extras/")
async def get_member_extras(current_user: AuthenticatedClient, member_id: str):
    """Get member extras data."""
    return db.get_member_extras(member_id)

@app.get("/v1/member/authorizations/")
async def get_member_authorizations(current_user: AuthenticatedClient, member_id: str):
    """Get member authorizations."""
    return db.get_member_authorizations(member_id)

@app.get("/v1/member/notes/")
async def get_member_notes(current_user: AuthenticatedClient, member_id: str):
    """Get member notes."""
    return db.get_member_notes(member_id)

@app.get("/v1/member/last_updated/")
async def get_member_last_updated(current_user: AuthenticatedClient, member_id: str):
    """Get member last updated timestamp."""
    return {"last_updated": db.get_member_last_updated(member_id)}

@app.get("/v1/member/last_wa_sync/")
async def get_last_wa_sync(current_user: AuthenticatedClient):
    """Get last Wild Apricot sync time."""
    return {"last_sync": db.get_last_wa_sync_time()}

@app.get("/v1/member/roles/")
async def get_member_roles(current_user: AuthenticatedClient, member_id: str):
    """Get member roles within Deep Harbor itself."""
    return {"roles": db.get_member_roles(member_id)}

@app.get("/v1/member/entry_logs/")
async def get_member_entry_logs(current_user: AuthenticatedClient, member_id: str):
    """Get member entry logs."""
    return {"entry_logs": db.get_member_entry_logs(member_id)}

###############################################################################
# Member POST endpoints
###############################################################################

@app.post("/v1/member/identity/")
async def update_member_identity(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Add or update member identity information."""
    data = await request.json()
    logger.debug(f"In update_member_identity with {data}")
    return db.add_update_identity(data)

@app.post("/v1/member/change_email_address/")
async def change_member_email_address(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Change member email address."""
    data = await request.json()
    logger.debug(f"In change_member_email_address with {data}")
    return db.change_email_address(data)

@app.post("/v1/member/connections/")
async def update_member_connections(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member connections."""
    data = await request.json()
    logger.debug(f"In update_member_connections with {data}")
    return db.add_update_connections(x_member_id, data)

@app.post("/v1/member/status/")
async def update_member_status(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member status."""
    data = await request.json()
    logger.debug(f"In update_member_status with {data}")
    return db.add_update_status(x_member_id, data)

@app.post("/v1/member/forms/")
async def update_member_forms(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member forms data."""
    data = await request.json()
    logger.debug(f"In update_member_forms with {data}")
    return db.add_update_forms(x_member_id, data)

@app.post("/v1/member/access/")
async def update_member_access(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member access data."""
    data = await request.json()
    logger.debug(f"In update_member_access with {data}")
    return db.add_update_access(x_member_id, data)

@app.post("/v1/member/extras/")
async def update_member_extras(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member extras data."""
    data = await request.json()
    logger.debug(f"In update_member_extras with {data}")
    return db.add_update_extras(x_member_id, data)

@app.post("/v1/member/notes/")
async def update_member_notes(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member notes."""
    data = await request.json()
    logger.debug(f"In update_member_notes with {data}")
    return db.add_update_notes(x_member_id, data)

@app.post("/v1/member/authorizations/")
async def update_member_authorizations(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[str, Header()],
):
    """Add or update member authorizations."""
    data = await request.json()
    logger.debug(f"In update_member_authorizations with {data}")
    return db.add_update_authorizations(x_member_id, data)

@app.post("/v1/member/wa_sync_time/")
async def update_wa_sync_time(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Update Wild Apricot sync time."""
    data = await request.json()
    logger.debug(f"In update_wa_sync_time with {data}")
    return db.update_last_wa_sync_time(data["last_sync"])

###############################################################################
# Bulk endpoints
###############################################################################

@app.get("/v1/members/names_and_emails/")
async def get_all_member_names_and_emails(current_user: AuthenticatedClient):
    """Get names and email addresses for all members."""
    return {"members": db.get_all_member_names_and_emails()}

@app.get("/v1/authorizations/available/")
async def get_available_authorizations(current_user: AuthenticatedClient):
    """Get all available authorizations."""
    return {"available_authorizations": db.get_available_authorizations()}

###############################################################################
# Deep Harbor specific endpoints (e.g. user activity on websites)
###############################################################################

@app.post("/v1/dh/user_activity/")
async def log_user_activity(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Log user activity on Deep Harbor websites."""
    data = await request.json()
    logger.debug(f"In log_user_activity with {data}")
    return db.log_user_activity(data)