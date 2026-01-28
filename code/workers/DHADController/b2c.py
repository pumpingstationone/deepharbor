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
        'accountEnabled': True,
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
            'password': 'P@ssw0rd1234!'
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