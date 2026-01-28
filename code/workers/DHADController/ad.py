from ms_active_directory import ADDomain
import base64
from ldap3 import ALL_ATTRIBUTES

from config import config
from dhs_logging import logger

###############################################################################
# Active Directory setup
###############################################################################

# Establishes our connection to active directory
def create_session():
    logger.info("Creating Active Directory session")
    
    ad_username = config['active_directory']['username']
    ad_password = config['active_directory']['password']
    ad_domain_name = config['active_directory']['domain_name']
    ad_ip = config['active_directory']['server_ip']
    
    ldap_server = f'ldaps://{ad_ip}'
    
    domain = ADDomain(ad_domain_name, 
                      ldap_servers_or_uris=[ldap_server], 
                      encrypt_connections=True)
    
    # This is just to verify that we've connected successfully
    curr_time = domain.find_current_time()
    logger.info(f"Connected to AD server. Current AD time: {curr_time}")
    
    # All the work will be done with this session
    session = domain.create_session_as_user(ad_username, ad_password)
    return session

def close_session(session):
    logger.info("Closing Active Directory session")
    session.close()

    
###############################################################################
# Active Directory operations
###############################################################################

def get_user_by_username(session, username):
    logger.info(f"Retrieving user by username: {username}")
    user = session.find_user_by_sam_name(username)
    logger.debug(f"Found {user.distinguished_name}")
    return user

def get_groups_by_username(session, username):
    groups = session.find_groups_for_user(username)
    logger.debug(f'{username} is in these groups: {groups}')

    return groups

def add_user_to_group(session, username, group_name):
    # We need to get the base DN so we can add the user to the group
    base_group_dn  = config['active_directory_groups']['tool_base_DN']
    full_group_dn = f'CN={group_name},{base_group_dn}'
    
    session.add_users_to_group(f'[{username}]', [group_name])
    logger.info(f"User {username} added to group {group_name}")
    
def remove_user_from_group(session, username, group_name):
    # We need to get the base DN so we can add the user to the group
    base_group_dn  = config['active_directory_groups']['tool_base_DN']
    full_group_dn = f'CN={group_name},{base_group_dn}'
    
    session.remove_users_from_group(f'[{username}]', [group_name])
    logger.info(f"User {username} added to group {group_name}")
    
def create_user(session, 
                username, 
                password, 
                first_name, 
                last_name, 
                email_address,
                common_name,
                supports_legacy_behavior=False):
    logger.info(f"Creating new user: {username}")
    
    user = session.create_user(
        sam_name=username,
        user_password=password,
        first_name=first_name,
        last_name=last_name,
        common_name=common_name,
        object_location=config['active_directory']['member_DN'],
        supports_legacy_behavior=supports_legacy_behavior,
        mail=email_address,
        userPrincipalName=email_address # so the user can log in with email
    )
    
    logger.info(f"User {username} created with DN: {user.distinguished_name}")
    return user

def delete_user(session, username):
    logger.info(f"Deleting user: {username}")
    
    session.delete_user_by_common_name(username=username, object_location=config['active_directory']['member_DN']) 
    
    logger.info(f"User {username} deleted successfully")

def set_user_enabled(session, username, enabled=True):
    action = "Enabling" if enabled else "Disabling"
    logger.info(f"{action} user: {username}")
    
    user = session.find_user_by_sam_name(username)
    if enabled:
        session.enable_account(user)
    else:
        session.disable_account(user)
    
    logger.info(f"User {username} successfully {'enabled' if enabled else 'disabled'}")

# If you're calling this function, it's likely because you're doing
# B2C stuff or something that requires the universally-unique ID
# of the user in Active Directory
# username is sAMAccountName
def get_ad_object_id(session, username):
    logger.info(f"Retrieving immutable ID for user: {username}")
    
    users = session.find_users_by_attribute('sAMAccountName', username, 
                                         attributes_to_lookup=[ALL_ATTRIBUTES])
    if not users:
        logger.error(f"User {username} not found in Active Directory")
        return None
    
    user = users[0]
    # Remove curly braces from GUID
    ad_object_id = user.all_attributes['objectGUID'].strip('{}')
   
    return ad_object_id

def get_current_datetime():
    logger.info("Retrieving current date and time from Active Directory")
    
    ad_username = config['active_directory']['username']
    ad_password = config['active_directory']['password']
    ad_domain_name = config['active_directory']['domain_name']
    ad_ip = config['active_directory']['server_ip']
    
    ldap_server = f'ldaps://{ad_ip}'
    
    domain = ADDomain(ad_domain_name, 
                      ldap_servers_or_uris=[ldap_server], 
                      encrypt_connections=True)
    
    # This is just to verify that we've connected successfully
    current_time = domain.find_current_time()
    
    logger.info(f"Current date and time from active directory: {current_time}")
    return current_time