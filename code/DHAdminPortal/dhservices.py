import email
import requests

from dhs_logging import logger
from config import config

# This module is where we invoke the service endpoints of Deep Harbor

###############################################################################
## DHService API configuration
###############################################################################

# This is the base URL for our DHService API
DH_API_BASE_URL = config.get("dh_services", "api_base_url")
# This is the client ID and secret for our DHService API
DH_CLIENT_ID = config.get("dh_services", "client_name")
DH_CLIENT_SECRET = config.get("dh_services", "client_secret")

###############################################################################
## DHEquipment API configuration
###############################################################################

EQUIP_API_BASE_URL = config.get("dh_equipment", "api_base_url", fallback="http://localhost/dh/equipment")
EQUIP_CLIENT_ID = config.get("dh_equipment", "client_name", fallback="dev-admin-portal")
EQUIP_CLIENT_SECRET = config.get("dh_equipment", "client_secret", fallback="secret")

_equip_tokens = {}


def _get_equip_token() -> str:
    """Get a cached OAuth2 token for the DHEquipment service."""
    import time
    if EQUIP_API_BASE_URL in _equip_tokens:
        return _equip_tokens[EQUIP_API_BASE_URL]
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{EQUIP_API_BASE_URL}/token",
                data={"username": EQUIP_CLIENT_ID, "password": EQUIP_CLIENT_SECRET},
                timeout=10,
            )
            resp.raise_for_status()
            token = resp.json()["access_token"]
            _equip_tokens[EQUIP_API_BASE_URL] = token
            return token
        except requests.exceptions.ConnectionError:
            if attempt == 0:
                time.sleep(1)
    raise RuntimeError("Could not connect to DHEquipment token endpoint")


def _equip_headers(token: str, member_id=None, permissions=None, role=None) -> dict:
    import json as _json
    h = {"Authorization": f"Bearer {token}"}
    if member_id:
        h["X-Member-ID"] = str(member_id)
    if permissions:
        h["X-Member-Permissions"] = _json.dumps(permissions)
    if role:
        h["X-Member-Role"] = role
    return h


def equip_get(path: str, member_id=None, permissions=None, role=None, params=None):
    """GET from DHEquipment API with retry on 401."""
    for attempt in range(2):
        if attempt == 1:
            _equip_tokens.pop(EQUIP_API_BASE_URL, None)
        token = _get_equip_token()
        resp = requests.get(
            f"{EQUIP_API_BASE_URL}{path}",
            headers=_equip_headers(token, member_id, permissions, role),
            params=params, timeout=15,
        )
        if resp.status_code == 401 and attempt == 0:
            _equip_tokens.pop(EQUIP_API_BASE_URL, None)
            continue
        resp.raise_for_status()
        return resp.json()


def equip_put(path: str, body: dict, member_id=None, permissions=None, role=None):
    """PUT to DHEquipment API with retry on 401."""
    for attempt in range(2):
        if attempt == 1:
            _equip_tokens.pop(EQUIP_API_BASE_URL, None)
        token = _get_equip_token()
        resp = requests.put(
            f"{EQUIP_API_BASE_URL}{path}",
            headers=_equip_headers(token, member_id, permissions, role),
            json=body, timeout=15,
        )
        if resp.status_code == 401 and attempt == 0:
            _equip_tokens.pop(EQUIP_API_BASE_URL, None)
            continue
        resp.raise_for_status()
        return resp.json()


###############################################################################
# Service functions to call Deep Harbor API endpoints
###############################################################################


# Our function to get an access token from DHService using oauth2 client 
# credentials flow
def get_access_token(username: str, password: str) -> str:
    url = f"{DH_API_BASE_URL}/token"
    response = requests.post(url, data={"username": username, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]

# Our function to get the current user from DHService
def get_member_id(access_token: str, email_address: str):
    url = f"{DH_API_BASE_URL}/v1/member/id"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, params={"email_address": email_address})
    response.raise_for_status()
    return response.json()

# Our function to search for members from DHService
def search_members(access_token: str, query: str):
    url = f"{DH_API_BASE_URL}/v1/member/search/"
    print(f"Searching for member '{query}' at {url}...")
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"query": query}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# List members with pagination — supports optional search query
def list_members(access_token: str, query: str = None, page: int = 1,
                 per_page: int = 25, sort: str = "date_added", order: str = "desc"):
    url = f"{DH_API_BASE_URL}/v1/member/list/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"page": page, "per_page": per_page, "sort": sort, "order": order}
    if query:
        params["query"] = query
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

# This call is to determine if there is already a member with a given
# username. It returns true if the username is taken, false otherwise.
def is_username_taken(access_token: str, username: str) -> bool:
    url = f"{DH_API_BASE_URL}/v1/member/username_check/"
    logger.debug(f"Checking if username '{username}' is taken...")
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"username": username}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    return not data.get("available", False)

# Our function to get member identity from DHService
def get_member_identity(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/identity/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get all of the relevant member data from DHService.
# This does not return _everything_, but it does return the main
# sections of member data needed for the member portal.
def get_full_member_info(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/full_info/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def resolve_member_display_name(access_token: str, member_id):
    """Resolve identity name fields for a member by ID. Returns None on 404."""
    url = f"{DH_API_BASE_URL}/v1/member/display_name/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params, timeout=5)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()

def search_onboarder_candidates(access_token: str, query: str = "", limit: int = 20):
    """Typeahead search for the onboarder picker."""
    url = f"{DH_API_BASE_URL}/v1/onboarder_search/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"query": query, "limit": limit}
    response = requests.get(url, headers=headers, params=params, timeout=5)
    response.raise_for_status()
    return response.json()

# Our function to get member roles from DHService
def get_member_roles(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/roles/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member status from DHService
def get_member_status(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/status/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member forms from DHService
def get_member_forms(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/forms/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member connections from DHService
def get_member_connections(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/connections/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member extras from DHService
def get_member_extras(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/extras/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member authorizations from DHService
def get_member_authorizations(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/authorizations/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member notes from DHService
def get_member_notes(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/notes/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def get_member_access(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/access/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def get_member_entry_logs(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/entry_logs/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Get member last updated time from DHService
def get_member_last_updated(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/last_updated/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"member_id": member_id}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def get_available_authorizations(access_token: str):
    url = f"{DH_API_BASE_URL}/v1/authorizations/available/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_available_membership_levels(access_token: str):
    url = f"{DH_API_BASE_URL}/v1/membership_levels/available/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

#
# Endpoints to save changes to member data
#
def add_member(access_token: str, identity_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/identity/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url, headers=headers, json=identity_data)
    response.raise_for_status()
    return response.json()

def update_member_status(access_token: str, member_id: str, status_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/status/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=status_data)
    response.raise_for_status()
    return response.json()

def update_member_identity(access_token: str, member_id: str, identity_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/identity/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=identity_data)
    response.raise_for_status()
    return response.json()

def update_member_roles(access_token: str, member_id: str, roles_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/roles/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=roles_data)
    response.raise_for_status()
    return response.json()

def update_member_extras(access_token: str, member_id: str, extras_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/extras/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=extras_data)
    response.raise_for_status()
    return response.json()

def update_member_authorizations(access_token: str, member_id: str, auth_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/authorizations/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-member-id": member_id  # FastAPI expects dashes, not underscores, which came as a big surprise
    }
    logger.debug(f"Sending authorization update - member_id: {member_id}, data: {auth_data}")
    response = requests.post(url, headers=headers, json=auth_data)
    logger.debug(f"Response status: {response.status_code}")
    if not response.ok:
        logger.error(f"Error response: {response.text}")
    response.raise_for_status()
    return response.json()

def update_member_notes(access_token: str, member_id: str, notes_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/notes/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=notes_data)
    response.raise_for_status()
    return response.json()

def update_member_access(access_token: str, member_id: str, access_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/access/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=access_data)
    response.raise_for_status()
    return response.json()

def update_member_forms(access_token: str, member_id: str, forms_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/forms/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=forms_data)
    response.raise_for_status()
    return response.json()

def update_member_connections(access_token: str, member_id: str, connections_data: dict):
    url = f"{DH_API_BASE_URL}/v1/member/connections/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    params = {"member_id": member_id}
    response = requests.post(url, headers=headers, params=params, json=connections_data)
    response.raise_for_status()
    return response.json()

#
# Endpoint to log user activity
#
def log_user_activity(access_token: str, member_id: str, activity_data: dict):
    url = f"{DH_API_BASE_URL}/v1/dh/user_activity/"
    headers = {"Authorization": f"Bearer {access_token}"}
    headers["X-Member-ID"] = str(member_id)
    # Add member_id to the activity_data at the same level as activity_details
    payload = {"member_id": member_id, **activity_data}
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

###############################################################################
# Space endpoints (access logs, etc.)
###############################################################################

def get_access_logs(access_token: str, start_date: str, end_date: str):
    url = f"{DH_API_BASE_URL}/v1/space/access_logs/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"start_date": start_date, "end_date": end_date}
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

###############################################################################
# Admin endpoints (roles management, assign roles)
###############################################################################

def get_all_roles(access_token: str):
    url = f"{DH_API_BASE_URL}/v1/admin/roles/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()

def create_role(access_token: str, name: str, permission: dict):
    url = f"{DH_API_BASE_URL}/v1/admin/roles/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url, headers=headers, json={"name": name, "permission": permission}, timeout=10)
    response.raise_for_status()
    return response.json()

def update_role(access_token: str, role_id: int, name: str, permission: dict):
    url = f"{DH_API_BASE_URL}/v1/admin/roles/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.put(url, headers=headers, json={"id": role_id, "name": name, "permission": permission}, timeout=10)
    response.raise_for_status()
    return response.json()

def assign_role_to_member(access_token: str, member_id: int, role_id: int):
    url = f"{DH_API_BASE_URL}/v1/admin/assign_role/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url, headers=headers, json={"member_id": member_id, "role_id": role_id}, timeout=10)
    response.raise_for_status()
    return response.json()

def get_members_with_roles(access_token: str):
    url = f"{DH_API_BASE_URL}/v1/admin/members_with_roles/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()

def remove_role_from_member(access_token: str, member_id: int):
    url = f"{DH_API_BASE_URL}/v1/admin/remove_role/"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post(url, headers=headers, json={"member_id": member_id}, timeout=10)
    response.raise_for_status()
    return response.json()

###############################################################################
# Contacts endpoints
# These endpoints manage contacts that are not members (i.e. no member ID)
###############################################################################
def search_contacts_by_email(access_token: str, email_address: str):
    url = f"{DH_API_BASE_URL}/v1/contacts/search_by_email/"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"email_address": email_address}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()
