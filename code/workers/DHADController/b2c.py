import msal
import requests
import msal
import requests
from ldap3 import ALL_ATTRIBUTES
import base64

from config import config
from dhs_logging import logger

###############################################################################
# Azure B2C operations
###############################################################################

# Must call this first!
def get_access_token():
    logger.info("Acquiring access token for Microsoft Graph API")
    
    # Get all the necessary config values
    b2c_tenant_name = config['azure_b2c']['tenant_name']
    b2c_tenant_id = config['azure_b2c']['tenant_id']
    client_id = config['azure_b2c']['client_id']
    client_secret = config['azure_b2c']['client_secret']
    
    # Build the authority URL - gonna assume they're not changing
    # the base URL anytime soon
    authority = f'https://login.microsoftonline.com/{b2c_tenant_id}'
    
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )
    
    # Acquire token for Microsoft Graph
    result = app.acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])

    if 'access_token' in result:
        access_token = result['access_token']
        logger.info('Successfully authenticated with Azure B2C')
        return access_token
    else:
        logger.error(f"Error: {result.get('error')}")
        logger.error(f"Description: {result.get('error_description')}")
        
    # If we're here, then the authentication failed :(
    return None

# This is a helper function that we can call to look up the B2C user ID based on the AD object ID.
# Note there's also another version of this function called get_b2c_user_id_by_email that looks 
# up the B2C user ID based on the email address instead of the AD object ID. 
# We can use either of these functions to find the B2C user ID depending on what information 
# we have available, though email is probably easier :P
def get_b2c_user_id_by_ad_object_id(access_token, ad_object_id):
    logger.info(f"Looking up B2C user with AD Object ID: {ad_object_id}")
    
    # Convert GUID to base64 to match the onPremisesImmutableId format in B2C
    immutable_id = base64.b64encode(ad_object_id.encode()).decode()
    
    graph_endpoint = f"https://graph.microsoft.com/v1.0/users?$filter=onPremisesImmutableId eq '{immutable_id}'"
    
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    response = requests.get(graph_endpoint, headers=headers)
    
    if response.status_code == 200:
        users = response.json().get('value', [])
        if users:
            b2c_user_id = users[0]['id']
            logger.info(f"Found B2C user ID: {b2c_user_id} for AD Object ID: {ad_object_id}")
            return b2c_user_id
        else:
            logger.warning(f"No B2C user found with AD Object ID: {ad_object_id}")
            return None
    else:
        logger.error(f"Error querying Microsoft Graph API: {response.status_code}")
        logger.error(response.json())
        return None

# Same idea as get_b2c_user_id_by_ad_object_id but looking up the 
# user by their email address instead of AD object ID.
def get_b2c_user_id_by_email(access_token, email_address):
    logger.info(f"Looking up B2C user with email address: {email_address}")
    
    graph_endpoint = f"https://graph.microsoft.com/v1.0/users?$filter=identities/any(id:id/issuerAssignedId eq '{email_address}' and id/issuer eq '{config['azure_b2c']['tenant_name']}.onmicrosoft.com')"
    
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    response = requests.get(graph_endpoint, headers=headers)
    
    if response.status_code == 200:
        users = response.json().get('value', [])
        if users:
            b2c_user_id = users[0]['id']
            logger.info(f"Found B2C user ID: {b2c_user_id} for email address: {email_address}")
            return b2c_user_id
        else:
            logger.warning(f"No B2C user found with email address: {email_address}")
            return None
    else:
        logger.error(f"Error querying Microsoft Graph API: {response.status_code}")
        logger.error(response.json())
        return None

# Creates the user in Azure B2C. Note that ad_object_id
# comes from ad.get_ad_object_id so make sure to call that
# first to get that value
def create_user_in_b2c(access_token,
                       dh_id,
                       username,
                       password,
                       first_name,
                       last_name,
                       email_address,
                       ad_object_id):
    logger.info(f"Gonna create {first_name} {last_name} with username {username} in B2C")
    
     # Convert GUID to base64
    immutable_id = base64.b64encode(ad_object_id.encode()).decode()
    
    b2c_tenant_name = config['azure_b2c']['tenant_name']
    extension_app_id = config['azure_b2c']['extensions_app_id'].replace('-','')
    
    graph_endpoint = 'https://graph.microsoft.com/v1.0/users'

    # Okay, here we go...
    user_data = {
        'accountEnabled': False,
        'displayName': f'{first_name} {last_name}',
        'mailNickname': username,
        'identities': [
            {
                'signInType': 'userName',
                'issuer': f'{b2c_tenant_name}.onmicrosoft.com',
                'issuerAssignedId': username
            },
            {
                'signInType': 'emailAddress',
                'issuer': f'{b2c_tenant_name}.onmicrosoft.com',
                'issuerAssignedId': email_address
            },
        ],
        'passwordProfile': {
            'forceChangePasswordNextSignIn': False,
            'password': password
        },
        'passwordPolicies': 'DisablePasswordExpiration,DisableStrongPassword',
        'givenName': first_name,
        'surname': last_name,
        'mail': email_address,
        'onPremisesImmutableId': immutable_id,  # Store AD object GUID for sync
        # Extension attributes to store AD Object GUID and DH ID
        f'extension_{extension_app_id}_ADObjectGUID': ad_object_id,
        f'extension_{extension_app_id}_CRMNumber': f'{dh_id}'
    }

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    response = requests.post(graph_endpoint, json=user_data, headers=headers)

    if response.status_code == 201:
        b2c_user = response.json()
        logger.info(f"User created successfully in Azure B2C")
        logger.info(f"User ID: {b2c_user['id']}")
        logger.info(f"Identities: {b2c_user.get('identities', [])}")
        logger.info(f"AD Object GUID: {ad_object_id}")
        logger.info(f"Immutable ID: {immutable_id}")
    else:
        logger.error(f"Error creating user: {response.status_code}")
        logger.error(response.json())


def update_user_in_b2c(first_name=None, last_name=None, email_address=None):
    logger.info(f"Updating user {email_address} in Azure B2C")
    
    access_token = get_access_token()
    if not access_token:
        logger.error("Cannot update user in B2C without access token")
        return False
    
    b2c_user_id = get_b2c_user_id_by_email(access_token, email_address)
    if not b2c_user_id:
        logger.error(f"Cannot update user in B2C without user ID for email {email_address}")
        return False
    
    graph_endpoint = f'https://graph.microsoft.com/v1.0/users/{b2c_user_id}'
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # Update the user's name
    user_data = {}
    if first_name:
        user_data['givenName'] = first_name
    if last_name:
        user_data['surname'] = last_name
    # And also update the display name
    if first_name or last_name:
        user_data['displayName'] = f"{first_name or ''} {last_name or ''}".strip()
        
    # For now, we're not updating the email address because 
    # that can cause issues with sign-in since the email address is one of the identities. 
    # If we want to support updating the email address in the future, we need to make 
    # sure to also update the corresponding identity in the identities array, 
    # and we also need to make sure that the new email address is not already in use by 
    # another user.
    """
    if email_address:
        user_data['mail'] = email_address
        # Also update the email identity
        user_data['identities'] = [
            {
                'signInType': 'emailAddress',
                'issuer': f"{config['azure_b2c']['tenant_name']}.onmicrosoft.com",
                'issuerAssignedId': email_address
            }
        ]
    """    
    response = requests.patch(graph_endpoint, json=user_data, headers=headers)
    
    if response.status_code == 204:
        logger.info(f"User updated successfully in Azure B2C")
    else:
        logger.error(f"Error updating user: {response.status_code}")
        logger.error(response.json())
        return False
    
    return True
    
def set_user_enabled(access_token, b2c_user_id, enabled=True):
    logger.info(f"{'Enabling' if enabled else 'Disabling'} user with B2C ID {b2c_user_id}")
    
    graph_endpoint = f'https://graph.microsoft.com/v1.0/users/{b2c_user_id}'
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # To enable or disable the user, we set accountEnabled property
    user_data = {
        'accountEnabled': enabled
    }
    
    response = requests.patch(graph_endpoint, json=user_data, headers=headers)
    
    if response.status_code == 204:
        logger.info(f"User {'enabled' if enabled else 'disabled'} successfully in Azure B2C")
    else:
        logger.error(f"Error {'enabling' if enabled else 'disabling'} user: {response.status_code}")
        logger.error(response.json())
        return False
    
    return True
