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
