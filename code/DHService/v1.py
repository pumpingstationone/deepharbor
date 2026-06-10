# *******************************************************************************
# This file contains all the v1 services
# *******************************************************************************

import secrets
from datetime import datetime
from time import time
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Request, Header
from pydantic import ValidationError

from fastapiapp import app
import auth
from dhs_logging import logger
import db
from models import ApiClientCreateIn, ApiClientPatchIn, SignupIdentityIn

# Type alias for authenticated client dependency
AuthenticatedClient = Annotated[auth.Client, Depends(auth.get_current_active_client)]

###############################################################################
# Helper functions
###############################################################################

def _create_member_getter(field_name: str, db_func, wrap_key: str = None):
    """Factory function to create member getter endpoints."""
    async def getter(
        current_user: AuthenticatedClient,
        member_id: int,
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
async def get_member_identity(current_user: AuthenticatedClient, member_id: int):
    """Get member identity information."""
    return db.get_member_identity(member_id)

@app.get("/v1/member/search_by_rfid_tag/")
async def search_members_by_rfid_tag(current_user: AuthenticatedClient, rfid_tag: str):
    """Search for members by RFID tag."""
    return db.search_members_by_rfid_tag(rfid_tag)

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

@app.get("/v1/member/list/")
async def list_members(current_user: AuthenticatedClient,
                       query: str = None, page: int = 1, per_page: int = 25,
                       sort: str = "date_added", order: str = "desc"):
    """List members with pagination. Optionally filter by search query."""
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    if query:
        return db.search_members_paginated(query, page, per_page, sort, order)
    return db.list_members(page, per_page, sort, order)

@app.get("/v1/member/username_check/")
async def check_member_username(current_user: AuthenticatedClient, username: str):
    """Check if a username is available."""
    return {"available": db.is_username_available(username)}

# This gets an amalgamation of all member data fields for a given member
@app.get("/v1/member/full_info/")
async def get_full_member_info(current_user: AuthenticatedClient, member_id: int):
    """Get full member information."""
    return db.get_full_member_info(member_id)

@app.get("/v1/member/display_name/")
async def get_member_display_name(current_user: AuthenticatedClient, member_id: int):
    """Get a member's identity name fields by ID. Used to render the onboarder
    name from a stored `forms.id_check_by` value. Returns 404 if the member
    does not exist."""
    name = db.resolve_member_display_name(member_id)
    if name is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Member not found")
    return name

@app.get("/v1/onboarder_search/")
async def onboarder_search(current_user: AuthenticatedClient, query: str = "", limit: int = 20):
    """Typeahead search for the admin portal onboarder picker. Ranks members
    holding `member.forms` change permission first."""
    return {"members": db.search_onboarder_candidates(query, limit)}

# These services are to get individual member data fields
@app.get("/v1/member/connections/")
async def get_member_connections(current_user: AuthenticatedClient, member_id: int):
    """Get member connections."""
    return db.get_member_connections(member_id)

@app.get("/v1/member/status/")
async def get_member_status(current_user: AuthenticatedClient, member_id: int):
    """Get member status."""
    return db.get_member_status(member_id)

@app.get("/v1/member/forms/")
async def get_member_forms(current_user: AuthenticatedClient, member_id: int):
    """Get member forms data."""
    return db.get_member_forms(member_id)

@app.get("/v1/member/access/")
async def get_member_access(current_user: AuthenticatedClient, member_id: int):
    """Get member access data."""
    return db.get_member_access(member_id)

@app.get("/v1/member/extras/")
async def get_member_extras(current_user: AuthenticatedClient, member_id: int):
    """Get member extras data."""
    return db.get_member_extras(member_id)

@app.get("/v1/member/authorizations/")
async def get_member_authorizations(current_user: AuthenticatedClient, member_id: int):
    """Get member authorizations."""
    return db.get_member_authorizations(member_id)

@app.get("/v1/member/notes/")
async def get_member_notes(current_user: AuthenticatedClient, member_id: int):
    """Get member notes."""
    return db.get_member_notes(member_id)

@app.get("/v1/member/last_updated/")
async def get_member_last_updated(current_user: AuthenticatedClient, member_id: int):
    """Get member last updated timestamp."""
    return {"last_updated": db.get_member_last_updated(member_id)}

@app.get("/v1/member/last_wa_sync/")
async def get_last_wa_sync(current_user: AuthenticatedClient):
    """Get last Wild Apricot sync time."""
    return {"last_sync": db.get_last_wa_sync_time()}

@app.get("/v1/member/roles/")
async def get_member_roles(current_user: AuthenticatedClient, member_id: int):
    """Get member roles within Deep Harbor itself."""
    return {"roles": db.get_member_roles(member_id)}

@app.get("/v1/member/entry_logs/")
async def get_member_entry_logs(current_user: AuthenticatedClient, member_id: int):
    """Get member entry logs."""
    return {"entry_logs": db.get_member_entry_logs(member_id)}

@app.get("/v1/member/authorization_changes/")
async def get_member_authorization_changes(current_user: AuthenticatedClient, member_id: int):
    """Get member authorization changes."""
    return db.get_member_authorization_changes(member_id)

@app.get("/v1/member/by_stripe_customer_id/")
async def get_member_by_stripe_customer_id(current_user: AuthenticatedClient, stripe_customer_id: str):
    """Get member by Stripe customer ID."""
    return db.get_member_by_stripe_customer_id(stripe_customer_id)

###############################################################################
# Member POST endpoints
###############################################################################

@app.post("/v1/member/identity/")
async def update_member_identity(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int | None, Header()] = None,
):
    """Add or update member identity information.

    When X-Member-ID is provided, updates that member by id. When omitted
    (signup path), falls back to matching an existing member by primary
    email or inserting a new row.
    """
    data = await request.json()
    logger.debug(f"In update_member_identity with member_id={x_member_id}, data={data}")
    # Signup / INSERT path only (no X-Member-ID): backstop the client-side
    # username maxlength/pattern that a direct POST can bypass. Not applied on
    # the update path, so editing legacy members whose AD username already
    # exceeds 16 chars (prod has them, up to 26) stays unaffected.
    if x_member_id is None:
        try:
            SignupIdentityIn.model_validate(data)
        except ValidationError:
            raise HTTPException(
                status_code=400,
                detail="Invalid active_directory_username: must be 1-16 characters "
                       "using letters, digits, underscore, or hyphen",
            )
    return db.add_update_identity(data, member_id=x_member_id)

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
    x_member_id: Annotated[int, Header()],
):
    """Add or update member connections."""
    data = await request.json()
    logger.debug(f"In update_member_connections with {data}")
    return db.add_update_connections(x_member_id, data)

@app.post("/v1/member/status/")
async def update_member_status(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int, Header()],
):
    """Add or update member status."""
    data = await request.json()
    logger.debug(f"In update_member_status with {data}")
    return db.add_update_status(x_member_id, data)

@app.post("/v1/member/forms/")
async def update_member_forms(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int, Header()],
):
    """Add or update member forms data."""
    data = await request.json()
    logger.debug(f"In update_member_forms with {data}")
    return db.add_update_forms(x_member_id, data)

@app.post("/v1/member/access/")
async def update_member_access(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int, Header()],
):
    """Add or update member access data."""
    data = await request.json()
    logger.debug(f"In update_member_access with {data}")
    return db.add_update_access(x_member_id, data)

@app.post("/v1/member/extras/")
async def update_member_extras(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int, Header()],
):
    """Add or update member extras data."""
    data = await request.json()
    logger.debug(f"In update_member_extras with {data}")
    return db.add_update_extras(x_member_id, data)

@app.post("/v1/member/notes/")
async def update_member_notes(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int, Header()],
):
    """Add or update member notes."""
    # So, here's how this works. The client will send us a JSON object with the following structure:
    # {
    #     "note": "This is a new note about the member.",
    #     "from": "Member Portal"  # or whatever the source of the note is,
    #     "timestamp": "2024-06-01T12:00:00Z"  # optional, if not provided we can use the current time
    # }    
    data = await request.json()
    logger.debug(f"In update_member_notes with {data}")
    if "timestamp" not in data:
        data["timestamp"] = datetime.now().isoformat()
    return db.add_update_notes(x_member_id, data)

@app.post("/v1/member/authorizations/")
async def update_member_authorizations(
    current_client: AuthenticatedClient,
    request: Request,
    x_member_id: Annotated[int, Header()],
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

@app.get("/v1/members/active_names_and_emails/")
async def get_all_active_member_names_and_emails(current_user: AuthenticatedClient):
    """Get names and email addresses for all active members."""
    return {"members": db.get_active_member_names_and_emails()}

@app.get("/v1/authorizations/available/")
async def get_available_authorizations(current_user: AuthenticatedClient):
    """Get all available authorizations."""
    return {"available_authorizations": db.get_available_authorizations()}

@app.get("/v1/membership_levels/available/")
async def get_available_membership_levels(current_user: AuthenticatedClient):   
    """Get all available membership levels."""
    return {"available_membership_levels": db.get_available_membership_levels()}

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

###############################################################################
# Contacts endpoints
# These endpoints manage contacts that are not members (i.e. no member ID)
###############################################################################

# This endpoint allows searching for contacts by email address which we use
# when a member is signing up; if they've already filled out a waiver, we
# can grab their info from the waiver table and pre-fill their info.
@app.get("/v1/contacts/search_by_email/")
async def search_contacts_by_email(current_user: AuthenticatedClient, email_address: str):
    """Search for contacts based on an email address."""
    return db.search_contacts_by_email(email_address)

##############################################################################
# Payment endpoints (e.g. for Stripe webhooks)
##############################################################################

@app.post("/v1/payment/stripe_webhook/")
async def handle_stripe_webhook(current_client: AuthenticatedClient, request: Request):
    """ We are passed the Stripe payload from ST2DH, and we want 
        to log it and then handle it as needed."""
    payload = await request.body()
    # We log the raw payload to the database, and then we can parse it and handle it as needed. 
    # This way we have a record of all Stripe events that we can refer back to if needed, and 
    # we can also analyze them later if we want to look for trends or patterns.
    return db.save_stripe_event(payload.decode("utf-8"))

# This endpoint is to get the list of products from our database, 
# which we can use to match the Stripe product ID to the membership level
# (among other things)
@app.get("/v1/products/")
async def get_products(current_user: AuthenticatedClient):
    """Get all products."""
    return {"products": db.get_products()}

###############################################################################
# Space endpoints (access logs, etc.)
###############################################################################

@app.get("/v1/space/access_logs/")
async def get_access_logs(
    current_user: AuthenticatedClient,
    start_date: str,
    end_date: str,
):
    """Get access logs for a date range."""
    return {"logs": db.get_access_logs(start_date, end_date)}

###############################################################################
# Admin endpoints (roles management, assign roles)
###############################################################################

@app.get("/v1/admin/roles/")
async def get_all_roles(current_user: AuthenticatedClient):
    """Get all roles."""
    return {"roles": db.get_all_roles()}

@app.post("/v1/admin/roles/")
async def create_role(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Create a new role."""
    data = await request.json()
    return db.create_role(data["name"], data["permission"])

@app.put("/v1/admin/roles/")
async def update_role(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Update an existing role."""
    data = await request.json()
    return db.update_role(data["id"], data["name"], data["permission"])

@app.get("/v1/admin/members_with_roles/")
async def get_members_with_roles(current_user: AuthenticatedClient):
    """Get all members who have a role assigned."""
    return {"members": db.get_members_with_roles()}

@app.post("/v1/admin/assign_role/")
async def assign_role_to_member(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Assign a role to a member, replacing any existing role."""
    data = await request.json()
    return db.assign_role_to_member(data["member_id"], data["role_id"])

@app.post("/v1/admin/remove_role/")
async def remove_role_from_member(
    current_client: AuthenticatedClient,
    request: Request,
):
    """Remove a member's role assignment."""
    data = await request.json()
    return db.remove_role_from_member(data["member_id"])

###############################################################################
# Admin endpoints (API client management)
###############################################################################

def _generate_client_secret() -> tuple[str, str]:
    plaintext = secrets.token_urlsafe(32)
    hashed = bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return plaintext, hashed


@app.get("/v1/admin/api_clients/")
async def list_api_clients(current_client: AuthenticatedClient):
    """List all OAuth2 API clients (metadata only — never includes secrets)."""
    return {"api_clients": db.list_api_clients()}


@app.get("/v1/admin/api_clients/{client_id}")
async def get_api_client(current_client: AuthenticatedClient, client_id: int):
    """Get a single API client's metadata."""
    row = db.get_api_client(client_id)
    if row is None:
        raise HTTPException(status_code=404, detail="API client not found")
    return row


@app.post("/v1/admin/api_clients/")
async def create_api_client(
    current_client: AuthenticatedClient,
    body: ApiClientCreateIn,
):
    """Create a new API client. Returns plaintext secret ONCE."""
    plaintext, hashed = _generate_client_secret()
    result = db.create_api_client(
        body.client_name,
        hashed,
        body.client_description,
        body.created_by_member_id,
    )
    if result.get("id") is None:
        msg = result.get("message") or "create failed"
        if msg == "client_name already exists":
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    logger.info(
        "API client created: id=%s name=%s by_member_id=%s acting_client=%s",
        result["id"], body.client_name, body.created_by_member_id,
        current_client.client_name,
    )
    return {
        "id": result["id"],
        "client_name": body.client_name,
        "plaintext_secret": plaintext,
    }


@app.post("/v1/admin/api_clients/{client_id}/rotate")
async def rotate_api_client(
    current_client: AuthenticatedClient,
    client_id: int,
):
    """Generate a new secret for an existing API client. Returns plaintext ONCE."""
    existing = db.get_api_client(client_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="API client not found")
    plaintext, hashed = _generate_client_secret()
    db.update_api_client_secret(client_id, hashed)
    logger.info(
        "API client secret rotated: id=%s name=%s acting_client=%s",
        client_id, existing["client_name"], current_client.client_name,
    )
    return {
        "id": client_id,
        "client_name": existing["client_name"],
        "plaintext_secret": plaintext,
    }


@app.patch("/v1/admin/api_clients/{client_id}")
async def patch_api_client(
    current_client: AuthenticatedClient,
    client_id: int,
    body: ApiClientPatchIn,
):
    """Toggle `disabled` and/or update `client_description`."""
    existing = db.get_api_client(client_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="API client not found")
    db.patch_api_client(client_id, body.disabled, body.client_description)
    logger.info(
        "API client patched: id=%s name=%s disabled=%s desc_changed=%s acting_client=%s",
        client_id, existing["client_name"], body.disabled,
        body.client_description is not None, current_client.client_name,
    )
    return db.get_api_client(client_id)