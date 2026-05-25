"""
HTTP client for Deep Harbor services.
Provides authenticated access to both DHService (member management)
and DHEquipment (equipment management) APIs.
"""

import requests
from config import config
from dhs_logging import logger

###############################################################################
# DHService (member management) configuration
###############################################################################

DH_API_BASE_URL = config.get("dh_services", "api_base_url", fallback="http://localhost/dh/service")
DH_CLIENT_ID = config.get("dh_services", "client_name", fallback="dev-equipment-portal")
DH_CLIENT_SECRET = config.get("dh_services", "client_secret", fallback="secret")

###############################################################################
# DHEquipment configuration
###############################################################################

EQUIP_API_BASE_URL = config.get("dh_equipment", "api_base_url", fallback="http://localhost/dh/equipment")
EQUIP_CLIENT_ID = config.get("dh_equipment", "client_name", fallback="dev-equipment-portal")
EQUIP_CLIENT_SECRET = config.get("dh_equipment", "client_secret", fallback="secret")

###############################################################################
# Token management
###############################################################################

_tokens = {}  # Cache tokens by base_url


def get_access_token(client_id: str, client_secret: str, base_url: str = None) -> str:
    """Get an OAuth2 access token from a DH service."""
    url = base_url or DH_API_BASE_URL
    cache_key = url
    if cache_key in _tokens:
        return _tokens[cache_key]
    return _fetch_token(client_id, client_secret, url)


def _fetch_token(client_id: str, client_secret: str, base_url: str, retries: int = 2) -> str:
    """Fetch a fresh token and store it in the cache. Retries on transient errors (502/503/connection)."""
    import time
    last_exc = None
    for attempt in range(retries):
        try:
            response = requests.post(
                f"{base_url}/token",
                data={"username": client_id, "password": client_secret},
                timeout=10,
            )
            if response.status_code in (502, 503, 504) and attempt < retries - 1:
                time.sleep(1)
                continue
            response.raise_for_status()
            token = response.json()["access_token"]
            _tokens[base_url] = token
            return token
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(1)
    raise last_exc or requests.exceptions.ConnectionError(f"Could not reach {base_url}/token")


def _evict_token(base_url: str):
    """Remove a cached token so the next call re-fetches it."""
    _tokens.pop(base_url, None)


def _equip_request(method: str, path: str, member_id=None, permissions=None,
                   role=None, json=None, params=None, timeout=15):
    """Make an authenticated request to the equipment service, retrying once on 401."""
    for attempt in range(2):
        if attempt == 1:
            _evict_token(EQUIP_API_BASE_URL)
        token = _fetch_token(EQUIP_CLIENT_ID, EQUIP_CLIENT_SECRET, EQUIP_API_BASE_URL) if attempt == 1 \
            else get_access_token(EQUIP_CLIENT_ID, EQUIP_CLIENT_SECRET, EQUIP_API_BASE_URL)
        headers = _member_headers(token, member_id, permissions, role)
        response = requests.request(
            method, f"{EQUIP_API_BASE_URL}{path}",
            headers=headers, json=json, params=params, timeout=timeout,
        )
        if response.status_code == 401 and attempt == 0:
            _evict_token(EQUIP_API_BASE_URL)
            continue
        response.raise_for_status()
        return response
    response.raise_for_status()  # re-raise if both attempts failed


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _member_headers(token: str, member_id: int = None, permissions: dict = None, role: str = None) -> dict:
    """Build headers with auth + member context for DHEquipment API calls."""
    import json
    headers = _auth_headers(token)
    if member_id:
        headers["X-Member-ID"] = str(member_id)
    if permissions:
        headers["X-Member-Permissions"] = json.dumps(permissions)
    if role:
        headers["X-Member-Role"] = role
    return headers


###############################################################################
# DHService — Member Management API
###############################################################################

def get_member_id(access_token: str, email_address: str):
    url = f"{DH_API_BASE_URL}/v1/member/id"
    response = requests.get(url, headers=_auth_headers(access_token),
                            params={"email_address": email_address}, timeout=10)
    response.raise_for_status()
    return response.json()


def get_member_roles(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/roles/"
    response = requests.get(url, headers=_auth_headers(access_token),
                            params={"member_id": member_id}, timeout=10)
    response.raise_for_status()
    return response.json()


def get_member_identity(access_token: str, member_id: str):
    url = f"{DH_API_BASE_URL}/v1/member/identity/"
    response = requests.get(url, headers=_auth_headers(access_token),
                            params={"member_id": member_id}, timeout=10)
    response.raise_for_status()
    return response.json()


def log_user_activity(access_token: str, member_id: str, activity_data: dict):
    url = f"{DH_API_BASE_URL}/v1/dh/user_activity/"
    response = requests.post(url, headers=_auth_headers(access_token),
                             params={"member_id": member_id},
                             json=activity_data, timeout=10)
    response.raise_for_status()
    return response.json()


###############################################################################
# DHEquipment — Equipment Management API
# All calls include member context headers for permission checking.
###############################################################################

def _equip_token():
    """Get a cached token for the equipment service."""
    return get_access_token(EQUIP_CLIENT_ID, EQUIP_CLIENT_SECRET, EQUIP_API_BASE_URL)


def _equip_get(path: str, member_id: int = None, permissions: dict = None,
               role: str = None, params: dict = None):
    return _equip_request("GET", path, member_id, permissions, role, params=params).json()


def _equip_post(path: str, data: dict, member_id: int = None,
                permissions: dict = None, role: str = None):
    return _equip_request("POST", path, member_id, permissions, role, json=data).json()


def _equip_patch(path: str, data: dict, member_id: int = None,
                 permissions: dict = None, role: str = None):
    return _equip_request("PATCH", path, member_id, permissions, role, json=data).json()


def _equip_put(path: str, data: dict, member_id: int = None,
               permissions: dict = None, role: str = None):
    return _equip_request("PUT", path, member_id, permissions, role, json=data).json()


def _equip_delete(path: str, member_id: int = None,
                  permissions: dict = None, role: str = None):
    _equip_request("DELETE", path, member_id, permissions, role)


# ── Convenience methods ──

def get_areas(member_id=None, permissions=None, role=None):
    return _equip_get("/v1/equipment/areas", member_id, permissions, role)

def get_equipment(member_id=None, permissions=None, role=None, **params):
    return _equip_get("/v1/equipment/items", member_id, permissions, role, params=params)

def get_tickets(member_id=None, permissions=None, role=None, **params):
    return _equip_get("/v1/equipment/tickets", member_id, permissions, role, params=params)

def get_dashboard_stats(member_id=None, permissions=None, role=None):
    return _equip_get("/v1/equipment/dashboard/stats", member_id, permissions, role)

def get_groups(member_id=None, permissions=None, role=None):
    return _equip_get("/v1/equipment/groups", member_id, permissions, role)

def get_schedules(member_id=None, permissions=None, role=None, **params):
    return _equip_get("/v1/equipment/schedules", member_id, permissions, role, params=params)

def get_auth_sessions(member_id=None, permissions=None, role=None, **params):
    return _equip_get("/v1/equipment/auth-sessions", member_id, permissions, role, params=params)

def get_maintenance_schedules(member_id=None, permissions=None, role=None, **params):
    return _equip_get("/v1/equipment/maintenance/schedules", member_id, permissions, role, params=params)

def get_maintenance_events(member_id=None, permissions=None, role=None, **params):
    return _equip_get("/v1/equipment/maintenance/events", member_id, permissions, role, params=params)

def get_config(key: str, member_id=None, permissions=None, role=None):
    return _equip_get(f"/v1/equipment/config/{key}", member_id, permissions, role)
