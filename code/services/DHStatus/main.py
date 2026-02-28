from enum import Enum
import os
import requests
import psycopg2
import psycopg2.extensions
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException

from config import config
from dhs_logging import logger
from email_template_handler import EmailTemplateHandler

# Our FastAPI app
app = FastAPI()

# Used to determine what kind of emails to send via DH2MG 
# The description is used to look up the appropriate email template in 
# DH2MG when sending emails based on status changes in this service.
class MembershipStatus(Enum):
    ACTIVE = (1, "Active membership")
    INACTIVE = (2, "Inactive membership")
    PENDING = (3, "Pending membership")
    def __init__(self, value, description):
        self._value_ = value
        self.description = description


###############################################################################
# Database Connection Context Manager
###############################################################################

@contextmanager
def get_db_connection():
    """Context manager for database connections with automatic cleanup."""
    schema = config["Database"]["schema"]
    conn = psycopg2.connect(
        dbname=config["Database"]["name"],
        user=config["Database"]["user"],
        password=config["Database"]["password"],
        host=config["Database"]["host"],
        options=f"-c search_path=dbo,{schema}",
    )
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        

###############################################################################
# Database functions
###############################################################################

# Get member identity from the database, which includes the active directory
# username needed for DH2AD service
def get_member_identity(member_id: str) -> str:
    # Fetch the member identity json from the database based on member_id
    logger.debug(f"Fetching member identity from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT identity FROM member WHERE id = %s", (member_id,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                raise ValueError(f"Member ID {member_id} not found")

def get_member_email(member_id: str) -> str:
    # Fetch the member email from the database based on member_id
    logger.debug(f"Fetching member email from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("select primary_email from v_member_id_email where id = %s", (member_id,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                raise ValueError(f"Member ID {member_id} not found")

# Gets the RFID tags associated with the member from the database
# Needed for the DH2RFID service
def get_member_tags(member_id: str) -> list:
    # Fetch the RFID tags associated with the member from the database
    logger.debug(f"Fetching RFID tags from database for member id {member_id}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Calls the stored procedure to get all tags for the member
            tag_sql = f"""
                select tag, wiegand_tag_num, status from get_all_tags_for_member({member_id});
            """
            cursor.execute(tag_sql)
            results = cursor.fetchall()
            tags = []
            for row in results:
                tags.append({"tag": row[0], "converted_tag": row[1], "status": row[2]})
            return tags

def get_email_template_name(status: MembershipStatus) -> tuple[str, str]:
    logger.debug(f"Getting email template name for status change: {status}")
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name, subject FROM email_templates WHERE use_for = %s", (status.description,))
            result = cursor.fetchone()
            if result:
                logger.debug(f"Email template name for status {status}: {result[0]}")
                return result[0], result[1]
            else:
                raise ValueError(f"No email template found for membership status {status}")
            
            
###############################################################################
# Healthcheck endpoint
###############################################################################

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": os.getenv("SERVICE_NAME", "DH_Status"),
    }

###############################################################################
# Service Endpoints Functions
#   These would be used to call other services as needed
###############################################################################

# This is the meta function that will find and call other services as needed
# If other services need to be called, this is where that logic would go
def perform_status_changes(member_id: str, change_type: str, membership_level: str) -> tuple[bool, str]:
    # Get the member identity to log who this is about
    
    member_identity = get_member_identity(member_id)
    logger.info(f"Processing status change for member identity: {member_identity}")
    first_name = member_identity.get("first_name", "Unknown")
    last_name = member_identity.get("last_name", "Unknown")
    email_address = get_member_email(member_id)
    
    logger.info(f"Member {first_name} {last_name} (ID {member_id} - {email_address}) status changed to {change_type}")
    logger.info(f"Membership level for member {first_name} {last_name} (ID {member_id} - {email_address}) changed to {membership_level}")
    
    #
    # Active directory changes via DH2AD
    #
    def perform_active_directory_changes():        
        dh2ad_url = config["DH2AD"]["endpoint_url"]
        dh2ad_payload = {
            "username": member_identity.get("active_directory_username"),
            "enabled": change_type.lower() == "active"
        }
        try:
            response = requests.post(dh2ad_url, json=dh2ad_payload)
            response.raise_for_status()
            logger.info(f"DH2AD response: {response.json()}")
        except requests.RequestException as e:
            logger.error(f"Error calling DH2AD service: {str(e)}")
            return False, str(e)
        
        return True, None
    
    #
    # RFID tag changes via DH2RFID
    #
    def perform_rfid_tag_changes():        
        dh2rfid_url = config["DH2RFID"]["base_endpoint_url"]
        if change_type.lower() == "active":
            dh2rfid_url += config["DH2RFID"]["add_tags_endpoint"]
        else:
            # For any status change that is not active, we will remove 
            # the tags from the board controller. This includes "Inactive", 
            # "Banned", etc.
            dh2rfid_url += config["DH2RFID"]["remove_tags_endpoint"]        

        dh2rfid_request = {
                "member_id": member_id,
                "first_name": first_name,
                "last_name": last_name,
                "tag": '',
                "converted_tag": ''
            }
        
        # Now we're getting the tags associated with the member and calling 
        # the DH2RFID service for each tag.
        tags = get_member_tags(member_id)
        for tag_entry in tags:
            # We are only processing ACTIVE tags here, in other words, tags that
            # are currently assigned to the member. If the member is being deactivated,
            # those tags will be removed from the board controller. 
            # If the member is being activated, those tags will be added
            # to the board controller.
            if tag_entry.get("status").lower() == "active":
                dh2rfid_request["tag"] = tag_entry.get("tag")
                dh2rfid_request["converted_tag"] = tag_entry.get("converted_tag")
                try:
                    response = requests.post(dh2rfid_url, json=dh2rfid_request)
                    response.raise_for_status()
                    logger.info(f"DH2RFID response for tag {tag_entry.get('tag')}: {response.json()}")
                except requests.RequestException as e:
                    logger.error(f"Error calling DH2RFID service for tag {tag_entry.get('tag')}: {str(e)}")
                    return False, str(e)
        
        return True, None
    
    #
    # Emails via DH2MG
    #
    def send_email(email_type):
        # We need to get an access token from DH2MG to authenticate our request. 
        # This is because the DH2MG service is protected and requires authentication 
        # for all requests. If it turns out we need to do more oauth2 stuff in the
        # future, we can always implement a more complete oauth2 flow here, but for now, 
        # we just use it for talking to DH2MG
        def get_access_token(username: str, password: str) -> str:
            url = f"{config["DH2MG"]["api_base_url"]}/token"
            response = requests.post(url, data={"username": username, "password": password})
            response.raise_for_status()
            return response.json()["access_token"]

        
        # First thing we need to get is the template name for the email we want to send based on the email type. The template name is what DH2MG uses to look up the appropriate email template in the database and determine which parameters are needed for that template. We will use the description field of the MembershipStatus enum to store the template name for each email type, so we can easily look it up here.
        try:
            # First we need to get the email template name for the email type. 
            # This is stored in the database and we can look it up based on the 
            # email type. The email type corresponds to the membership status 
            # change, so we can use that to look up the appropriate template.
            template_name, subject  = get_email_template_name(email_type)
            logger.info(f"Email template name for email type {email_type}: {template_name}")
            
            # Now we need to build the email parameters based on the template parameters 
            # that DH2MG expects for this template. We will use the EmailTemplateHandler 
            # class to get the required parameters for the template and then extract 
            # those parameters from the member identity and other data we have available. 
            # This way, we can ensure that we are sending all the necessary information to 
            # DH2MG for email generation without hardcoding any of the parameter names or 
            # values in this code.
            
            # We need to build a quick json object that contains all the data we have available that might be needed for the email template. This includes the member identity, the change type, and any other relevant information. The EmailTemplateHandler will then extract only the parameters that are needed for the specific template we are using.
            email_template_data = {
                "member_id": member_id,
                "first_name": first_name,
                "last_name": last_name,
                "email_address": email_address,
                "change_type": change_type,
                # We can add more data here as needed, such as the member's membership level, 
                # renewal date, etc. The EmailTemplateHandler will just ignore any data that 
                # is not needed for the specific template we are using.
            }
            
            # Okay, now we can use the EmailTemplateHandler to build the template 
            # parameters for the email we want to send. We will pass in the template 
            # name and the email template data, and it will return a dictionary of the 
            # parameters that we need to send to DH2MG for email generation.
            email_template_handler = EmailTemplateHandler(get_db_connection())
            template_parameters = email_template_handler.build_template_parameters(template_name, email_template_data)
            logger.info(f"Email template parameters for template {template_name}: {template_parameters}")

            # Okay, here we go...this json contains everything we're going to send
            # to DH2MG to generate the email based on the template. The "template" 
            # field is the name of the template we want to use, and the "variables" 
            # field contains the parameters that we want to pass to that template 
            # for email generation. The "to_email" and "subject" fields are also 
            # required for sending the email.
            template_email_message = {
                "to_email": email_address,
                "subject": subject,
                "template": template_name,
                "variables": template_parameters
            }
        
            dh2mg_url = config["DH2MG"]["api_base_url"]
            url = f"{dh2mg_url}/send_template_email/"
            # First we have to get an access token from DH2MG to authenticate our request. 
            # This is because the DH2MG service is protected and requires authentication 
            # for all requests.
            access_token = get_access_token(config["DH2MG"]["client_name"], 
                                            config["DH2MG"]["client_secret"])
            headers = {"Authorization": f"Bearer {access_token}"}
            response = requests.post(url, headers=headers, json=template_email_message)            
            response.raise_for_status()
            logger.info(f"DH2MG response: {response.json()}")
        except requests.RequestException as e:
            logger.error(f"Error calling DH2MG service: {str(e)}")
            return False, str(e)
        
        return True, None
    
    
    """
    Rules for status changes:
    - "Pending"
        The member is pending activation. No changes are made to active directory 
        or RFID tags at this point. This status is used for new members who have 
        signed up but have not yet been approved by an admin.
    - "Active"
        The member is active and should have an active directory account enabled 
        and their RFID tags added to the board controller.
    - Everything else (e.g. "Inactive", "Banned", etc.)
        The member is inactive and should have an active directory account 
        disabled and their RFID tags removed from the board controller.
    """
    
    # If the member is pending, we don't make any changes to active 
    # directory or RFID tags, but we *do* send them a welcome email via DH2MG 
    # to let them know that their account is pending and will be activated 
    # as soon as they come in for an ID check.
    if change_type.lower() == "pending":
        logger.info(f"Member {first_name} {last_name} (ID {member_id}) is pending activation. No changes will be made to active directory or RFID tags at this point.")
        
        # If the membership level is "New Member", we do *not* send a welcome email.
        # Why? They've only signed up in Deep Harbor, but have not yet chosen a membership level,
        # so we don't want to send them an email with info about completing the signup process
        # until they actually choose a membership level (i.e. set up a recurring payment in Stripe). 
        # Once they choose a membership level, their status will still be pending, but at least 
        # then we know they have completed the signup process and we can send them an email with 
        # info about next steps.
        if membership_level.lower() == "new member":
            logger.info(f"Member {first_name} {last_name} (ID {member_id}) has not chosen a membership level yet and has membership level 'New Member'. No welcome email will be sent at this time.")
            return True, None
        
        # Now let's send them a welcome email via DH2MG to let them know that their account is pending and will be activated as soon as they come in for an ID check.
        email_sent, email_error_message = send_email(MembershipStatus.PENDING)
        if email_sent is False:
            logger.error(f"Failed to send pending email via DH2MG for member id {member_id}: {email_error_message}")
            return False, f"Failed to send pending email via DH2MG: {email_error_message}"
        return True, None
     
    # Perform active directory changes for both "Active" and "Inactive"/"Banned" 
    # status changes. The logic for what to change in active directory 
    # is handled in the DH2AD worker, so we just need to call it 
    # with the necessary information and let it handle the rest.
    ad_changed, ad_error_message = perform_active_directory_changes()
    if ad_changed is False:
        logger.error(f"Failed to perform active directory changes for member id {member_id}: {ad_error_message}")
        return False, f"Failed to perform active directory changes: {ad_error_message}"

    # Perform RFID tag changes for both "Active" 
    # and "Inactive"/"Banned" status changes. The logic for 
    # what to change in RFID tags is handled in the DH2RFID worker, 
    # so we just need to call it with the necessary information and 
    # let it handle the rest.
    rfid_changed, rfid_error_message = perform_rfid_tag_changes()
    if rfid_changed is False:
        logger.error(f"Failed to perform RFID tag changes for member id {member_id}: {rfid_error_message}")
        return False, f"Failed to perform RFID tag changes: {rfid_error_message}"
    
    # Send email via DH2MG for "Active" and "Inactive"
    # We do not send an email if the status is "Banned"
    if change_type.lower() != "banned":
        logger.info(f"Member {first_name} {last_name} (ID {member_id}) status changed to {change_type}. Sending email notification via DH2MG.")
        email_sent, email_error_message = send_email(MembershipStatus.ACTIVE if change_type.lower() == "active" else MembershipStatus.INACTIVE)
        if email_sent is False:
            logger.error(f"Failed to send status change email via DH2MG for member id {member_id}: {email_error_message}")
            return False, f"Failed to send status change email via DH2MG: {email_error_message}"
    
    # If we reach here, all status changes were successful
    return True, None


###############################################################################
# Endpoint to status changes
###############################################################################

@app.post("/v1/change_status")
def change_status(request: dict):
    logger.debug(f"Received status change request: {request}")
    # Our dict looks like:
    # {'member_id': 1, 'change_type': 'status', 'change_data': {'donor': False, 'balance': 0.0, 'donations': 0.0, 'member_id': '1', 'member_since': '2018-05-12T00:00:00-05:00', 'renewal_date': None, 'membership_level': 'Area Host', 'membership_status': 'active', 'stripe_customer_id': None}}
    
    # Let's get the membership status from change_data
    change_data = request.get("change_data", {})
    membership_status = change_data.get("membership_status")
    membership_level = change_data.get("membership_level")

    changed_status, error_message = perform_status_changes(request.get("member_id"), membership_status, membership_level)        
    if error_message is None:
        error_message = ""
        
    if changed_status is True:
        logger.info(f"Successfully processed status change for member id {request.get('member_id')}")
    else:
        logger.error(f"Failed to process status change for member id {request.get('member_id')}: {error_message}")
        raise HTTPException(status_code=500, detail=f"Failed to process status change for member id {request.get('member_id')}: {error_message}")
    
    return {"processed": True}
