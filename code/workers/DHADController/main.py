from http.client import HTTPException
import json
import time
import os
import glob
import uuid
import datetime

from ldap3 import ALL_ATTRIBUTES

import ad
import b2c
from dhs_logging import logger
from config import config

###############################################################################
# Queue Configuration
###############################################################################

BASE_DIR = config["shared"]["SHARED_VOLUME_PATH"]
QUEUE_DIR = os.path.join(BASE_DIR, "queues")
if not os.path.exists(QUEUE_DIR):
    os.makedirs(QUEUE_DIR)
RESPONSE_DIR = os.path.join(BASE_DIR, "responses")
if not os.path.exists(RESPONSE_DIR):
    os.makedirs(RESPONSE_DIR)
PROCESSING_DIR = os.path.join(BASE_DIR, "processing")
if not os.path.exists(PROCESSING_DIR):
    os.makedirs(PROCESSING_DIR)


###############################################################################
# Active Directory / B2C Interaction Functions
###############################################################################
def get_datetime():
    try:
        current_time = ad.get_current_datetime()
        logger.info(f"Current AD date and time: {current_time}")
        return {
            "status": "success",
            "data": {
                "current_time": current_time.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error getting date and time from AD: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }

def create_user(username, first_name, last_name, email_address, dh_id):
    logger.debug(f"Creating user with username: {username}, first_name: {first_name}, last_name: {last_name}, email_address: {email_address}, dh_id: {dh_id}")
    try:
        # 1. Create user in Active Directory
        ad_session = ad.create_ad_session()
        password = ad.create_random_password()        
        supports_legacy_behavior = True  # This is needed for B2C to work properly
        
        user = ad.create_user(ad_session, 
                              username, 
                              password, 
                              first_name, 
                              last_name,                             
                              email_address, 
                              supports_legacy_behavior)
        
        # 2. Get the immutable AD object ID (GUID) for the user
        ad_object_id = ad.get_ad_object_id(ad_session, username)
        
        # 3. Create user in Azure B2C
        access_token = b2c.get_access_token()
        if not access_token:
            logger.error("Failed to acquire access token for Azure B2C")
            raise Exception("Failed to acquire access token for Azure B2C")
        
        b2c.create_user_in_b2c(access_token, 
                               dh_id, 
                               username, 
                               password, 
                               first_name, 
                               last_name, 
                               email_address, 
                               ad_object_id)
        
        # 4. *DISABLE* the user in AD and B2C by default - we will enable 
        # them when we get the "active" status update from DHStatus. 
        # This is important because we don't want the user to be able to 
        # log in before they are fully onboarded and have their status set 
        # to active. By default, when we create a user in AD, it is 
        # enabled, so we need to disable it explicitly. In B2C, we can set 
        # the accountEnabled property to false when we create the user, 
        # so it will be disabled by default.
        logger.info(f"Disabling user {username} in AD and B2C by default until they are activated")
        ad.set_user_enabled(ad_session, username, enabled=False)
        b2c.set_user_enabled(access_token, 
                             b2c.get_b2c_user_id_by_ad_object_id(access_token, ad_object_id), 
                             enabled=False)
        
         
        return {
            "status": "success",
            "data": {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "email_address": email_address,
                "ad_object_id": ad_object_id,
                "password": password,
                "dh_id": dh_id
            }
        }
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }

def update_user(ad_session, existing_user, username, first_name, last_name, email_address, dh_id):    
    logger.debug(f"Updating user with username: {username}, first_name: {first_name}, last_name: {last_name}, email_address: {email_address}, dh_id: {dh_id}")
    # Now we will update the user's information in AD based on the information in the request. 
    # For simplicity, let's assume we are only updating the first name, last name, 
    # and email address, but in the future we may want to update other attributes as well.
    # Note we're not updating the email address right now because that can be complicated 
    # and we want to make sure we have the right logic in place for that before we 
    # allow it to be updated.
    update_map = {
        'givenName': first_name,
        'sn': last_name,
        # Not going to do email right now 
        #'mail': email_address,
    }
    if ad.update_user(ad_session, existing_user, update_map):
        logger.info(f"User {username} information updated in AD")
    else:        
        logger.error(f"Failed to update user {username} information in AD")
        # We don't want to continue if we failed to update the user in AD, 
        # since that's the source of truth for the user's information. 
        # If we can't update the user in AD, then we shouldn't try to update it in 
        # B2C either since that could lead to inconsistencies. So we will return 
        # an error here and not proceed with updating B2C.
        return {
            "status": "failure",
            "error": f"Failed to update user {username} information in AD"
        }
    
    # Now we also want to update the user's information in B2C
    # We need to explicitly pass in the email address so we can look
    # up the B2C user by that
    if not b2c.update_user_in_b2c(first_name=first_name, last_name=last_name, email_address=email_address):
        logger.error(f"Failed to update user {username} information in B2C")
        # This is not ideal, but we will return an error here if we failed to update the user in B2C. 
        # The user's information in AD will still be updated, but at least we will know that there was an issue with updating B2C and we can investigate further. In the future, we may want to have a more robust way of handling errors like this (e.g. retrying the update to B2C a few times before giving up, etc.), but for now we will just return an error.
        return {
            "status": "failure",
            "error": f"Failed to update user {username} information in B2C"
        }
    
    # Yay it all worked!
    logger.info(f"User {username} information updated in AD and B2C")
    return {
        "status": "success",
        "data": {
            "operation": "sync_account_info",
            "username": username,
            "updated_fields": list(update_map.keys())
        }
    }

def set_user_enabled(username, enabled=True):
    try:
        ad_session = ad.create_ad_session()
        result = ad.set_user_enabled(ad_session, username, enabled=enabled)
        if result["status"] == "failure":
            logger.error(f"Failed to set user enabled state in Active Directory: {result['error']} - Does the user exist?")
            return {
                "status": "failure",
                "error": f"Failed to set user enabled state in Active Directory: {result['error']} - Does the user exist?"
            }

        # Okay cool if we're here, then we successfully set the user's enabled state in Active Directory. 
        # Now we also want to set the user's enabled state in B2C to match, since if a user is disabled in AD, 
        # they should also be disabled in B2C, and vice versa because if you can't log into the computers,
        # then you shouldn't also be able to log into anything else that is B2C-controlled.
        logger.info(f"User {username} enabled state set to {enabled} in Active Directory")

        # We want to get the email address of the user so we can look them up in B2C and 
        # set their enabled state there as well, since if they're disabled in AD, they should 
        # also be disabled in B2C.
        email_address = ad.get_email_by_username(ad_session, username)
        if not email_address:
            logger.warning(f"Could not retrieve email address for user {username}. This may cause issues with syncing enabled state to B2C.")

        # And also disable/enable in B2C if needed - we can look up the B2C user by the AD Object ID stored in the extension attribute
        ad_object_id = ad.get_ad_object_id(ad_session, username)
        access_token = b2c.get_access_token()
        if not access_token:
            logger.error("Failed to acquire access token for Azure B2C")
            raise Exception("Failed to acquire access token for Azure B2C")
        # If we have the email address, we can look up the B2C user by that, otherwise we will look up the B2C user by the AD Object ID stored in the extension attribute
        b2c_user_id = None
        if email_address:
            b2c_user_id = b2c.get_b2c_user_id_by_email(access_token, email_address)
            logger.debug(f"Looked up B2C user ID by email address {email_address}: {b2c_user_id}")
        if not b2c_user_id and ad_object_id:
            b2c_user_id = b2c.get_b2c_user_id_by_ad_object_id(access_token, ad_object_id)
            logger.debug(f"Looked up B2C user ID by AD Object ID {ad_object_id}: {b2c_user_id}")
        if b2c_user_id:            
            b2c.set_user_enabled(access_token, b2c_user_id, enabled=enabled)
        else:
            logger.warning(f"No corresponding B2C user found for AD user {username} with Object ID {ad_object_id}")
        return {
            "status": "success",
            "data": {
                "username": username,
                "action": "enabled" if enabled else "disabled"
            }
        }
    except Exception as e:
        logger.error(f"Error setting user enabled state: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }

def get_is_user_enabled(username):
    try:
        # Default to False if we can't get the enabled state from B2C 
        # for any reason, since AD is the source of truth for the user's 
        # enabled state, but we want to log the B2C enabled state if 
        # we can get it for informational purposes and to help with 
        # debugging if there are issues with enabled state not syncing 
        # properly between AD and B2C.
        b2c_enabled_state = False  
        
        ad_session = ad.create_ad_session()
        is_ad_enabled = ad.get_is_user_enabled(ad_session, username)
        if is_ad_enabled is None:
            logger.error(f"Failed to get user enabled state from Active Directory for user {username} - Does the user exist?")
            return {
                "status": "failure",
                "error": f"Failed to get user enabled state from Active Directory for user {username} - Does the user exist?"
            }
        logger.info(f"User {username} enabled state in Active Directory: {is_ad_enabled}")
        
        # Now let's also get the user's enabled state in B2C to compare
        email_address = ad.get_email_by_username(ad_session, username)
        if email_address:
            access_token = b2c.get_access_token()
            if access_token:
                b2c_user_id = b2c.get_b2c_user_id_by_email(access_token, email_address)
                if b2c_user_id:
                    b2c_enabled_state = b2c.get_user_enabled_status(access_token, b2c_user_id)
                    logger.info(f"User {username} enabled state in B2C: {b2c_enabled_state}")
                else:
                    logger.warning(f"Could not find B2C user for email address {email_address} to compare enabled state")
            else:
                logger.warning("Could not acquire access token for Azure B2C to compare enabled state")
        else:
            logger.warning(f"Could not retrieve email address for user {username} to compare enabled state in B2C")
        
        return {
            "status": "success",
            "data": {
                "username": username,
                "ad_enabled": is_ad_enabled,
                "b2c_enabled": b2c_enabled_state if email_address else None
            }
        }
    except Exception as e:
        logger.error(f"Error getting user enabled state: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }

def add_user_to_group(username, group_name):
    ad_session = ad.create_ad_session()
    try:
        success = ad.add_user_to_group(ad_session, username, group_name)
        if not success:
            logger.error(f"Failed to add user {username} to group {group_name}")
            return {
                "status": "failure",
                "error": f"Failed to add user {username} to group {group_name}"
            }
        logger.info(f"User {username} added to group {group_name}")
        return {
            "status": "success",
            "data": {
                "operation": "add_user_to_group",
                "username": username,
                "group_name": group_name
            }
        }
    except Exception as e:
        logger.error(f"Error adding user to group: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }

def remove_user_from_group(username, group_name):
    ad_session = ad.create_ad_session()
    try:
        success = ad.remove_user_from_group(ad_session, username, group_name)
        if not success:
            logger.error(f"Failed to remove user {username} from group {group_name}")
            return {
                "status": "failure",
                "error": f"Failed to remove user {username} from group {group_name}"
            }
        logger.info(f"User {username} removed from group {group_name}")
        return {
            "status": "success",
            "data": {
                "operation": "remove_user_from_group",
                "username": username,
                "group_name": group_name
            }
        }
    except Exception as e:
        logger.error(f"Error removing user from group: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }
        
 
def update_user_ssh_keys(username, ssh_keys):
    logger.debug(f"Updating user {username}'s SSH keys")
    ad_session = ad.create_ad_session()    
    try:
        success = ad.update_user(ad_session, username,
                                 {"altSecurityIdentities", ssh_keys})
        if not success:
            logger.error(f"Failed to update SSH keys for user: {username}")
            return {
                "status": "failure",
                "error": f"Failed to update SSH keys for user: {username}",
            }
        logger.info(f"Updated SSH keys for user {username}")
        return {
            "status": "success",
            "data": {
                "operation": "update_user_ssh_keys",
                "username": username,
                "ssh_keys": ssh_keys
            }
        }
    except Exception as e:
        logger.error(f"Error updating user {username}'s ssh keys: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }
def sync_account_info(request):
    logger.debug(f"Syncing account information with request: {request}")
    # Okay, first let's see if there's already an AD user in Active Directory 
    # with the same username as the one in the request. If there is, we 
    # will assume that this is the same user and we just need to update 
    # their information. If there isn't, then we will create a new user. 
    # This is a simplification and in the future we may want to have 
    # a more robust way of matching users (e.g. by email address or by a 
    # unique identifier), but for now we will go with this approach.
    try:
        username = request.get("username")
        if not username:
            return {
                "status": "failure",
                "error": "username is required in the request"
            }
            
        ad_session = ad.create_ad_session()
        existing_user = ad.get_user_by_username(ad_session, username)
        if existing_user:
            logger.info(f"User with username {username} already exists in AD. Updating information...")
            return update_user(ad_session,
                               existing_user,
                               username=username,
                               first_name=request.get("first_name"),
                               last_name=request.get("last_name"),
                               email_address=request.get("email_address"),
                               dh_id=request.get("dh_id"))
        else:
            logger.info(f"No existing user with username {username} found in AD. Creating new user...")
            # If there is no existing user, we will create a new user in AD and B2C with the information in the request. We can reuse the create_user function we defined earlier for this.
            return create_user(
                username=username,
                first_name=request.get("first_name"),
                last_name=request.get("last_name"),
                email_address=request.get("email_address"),
                dh_id=request.get("dh_id")
            )
    except Exception as e:
        logger.error(f"Error syncing account information: {e}")
        return {
            "status": "failure",
            "error": str(e)
        }
   
###############################################################################
# Message Queue Interaction Functions
###############################################################################

# This is the important function regarding payload handling - this is where 
# we will take the payload from the queue message and call the appropriate 
# functions to interact with Active Directory and B2C, and then return a 
# structured response that we can write back to the response file for the queue 
# message
def handle_message(msg_id, payload):
    operation = payload.get("operation")

    # What do we wanna do?
    if operation == "create_user":
        success_payload = create_user(
            username=payload.get("username"),
            first_name=payload.get("first_name"),
            last_name=payload.get("last_name"),
            email_address=payload.get("email_address"),
            dh_id=payload.get("dh_id")
        )
        if success_payload["status"] == "failure":
            return {
                "original_id": msg_id,
                "status": "failure",
                "error": success_payload["error"]
            }
        else:            
            return {
                "original_id": msg_id,
                "status": "success",
                "data": success_payload["data"]
            }
    elif operation == "set_user_enabled":
        success_payload = set_user_enabled(username=payload.get("username"), 
                                           enabled=payload.get("enabled", True))
        if success_payload["status"] == "failure":
            return {
                "original_id": msg_id,
                "status": "failure",
                "error": success_payload["error"]
            }
        else:
            return {
                "original_id": msg_id,
                "status": "success",
                "data": success_payload["data"]
            } 
    elif operation == "get_datetime":
        result_data = get_datetime()
        result_data["original_id"] = msg_id
        return result_data
    elif operation == "add_user_to_group":
        return add_user_to_group(username=payload.get("username"), 
                                 group_name=payload.get("group_dn"))
    elif operation == "remove_user_from_group":
        return remove_user_from_group(username=payload.get("username"), 
                                     group_name=payload.get("group_dn"))        
    elif operation == "sync_account_info":
        return sync_account_info(payload)
    elif operation == "get_is_user_enabled":
        return get_is_user_enabled(username=payload.get("username"))
    elif operation == "update_user_ssh_keys":
        return update_user_ssh_keys(username=payload.get("username"),
                                    ssh_keys=payload.get("ssh_keys"))
    else:
        result_data = {
            "original_id": msg_id,
            "status": "failure",
            "error": f"Unknown operation: {operation}"
        }
    
    return result_data

def process_queue():
    logger.info("DHADController Worker started. Monitoring queue...")
    
    while True:
        # Get list of .json files in queue
        queue_files = glob.glob(os.path.join(QUEUE_DIR, "*.json"))
        
        # Sort by creation time (optional, ensures FIFO)
        queue_files.sort(key=os.path.getmtime)

        if not queue_files:
            time.sleep(0.1)
            continue

        # Pick the oldest file
        current_file = queue_files[0]
        filename = os.path.basename(current_file)
        msg_id = filename.replace(".json", "")
        
        # 1. Get the message
        # Move it to a 'processing' folder to handle it
        processing_path = os.path.join(PROCESSING_DIR, filename)
        
        try:
            os.rename(current_file, processing_path)
        except FileNotFoundError:
            # Hmm, why is it not here? Maybe another process took it?
            continue

        try:
            # 2. Read and Process
            with open(processing_path, 'r') as f:
                data = json.load(f)
            
            logger.info(f"Processing {msg_id}: {data['payload']}")
            
            # Now handle the message
            message_data = handle_message(msg_id, data['payload']) 
            logger.debug(f"Result for {msg_id}: {message_data}")
            
            result_data = {
                "original_id": msg_id,
                "result": f"Processed '{data['payload']}'",
                "status": "success",
                "data": message_data
            }

            # 3. Write Response Atomically
            tmp_resp = os.path.join(BASE_DIR, f".tmp_resp_{msg_id}")
            final_resp = os.path.join(RESPONSE_DIR, filename)

            with open(tmp_resp, 'w') as f:
                json.dump(result_data, f)
                f.flush()
                os.fsync(f.fileno())
            # Rename is an atomic operation
            os.rename(tmp_resp, final_resp)
        except Exception as e:
            logger.error(f"Error processing {msg_id}: {e}")
        finally:
            # 4. Cleanup
            if os.path.exists(processing_path):
                os.remove(processing_path)
                
def main():
    # Start processing the queue  
    process_queue()

if __name__ == "__main__":
    main()
    # For testing purposes, let's just call create_user directly
    #result = create_user("zestyzest", "Zesty", "Zest", "zesty1234@example.com", "12345")
    #result = add_user_to_group("zestyzest", "Band Saw")
    #result = remove_user_from_group("zestyzest", "Band Saw")
    #print(result)
