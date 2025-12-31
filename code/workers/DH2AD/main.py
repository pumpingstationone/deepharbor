import os
from fastapi import FastAPI, HTTPException

from ad import ad
from b2c import b2c

from dhs_logging import logger

# Our FastAPI app
app = FastAPI()

###############################################################################
# Healthcheck endpoint
###############################################################################


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": os.getenv("SERVICE_NAME", "DH2AD")}

###############################################################################
# Endpoint to set up identities in Active Directory, creating users if needed
###############################################################################

@app.post("/v1/sync_account_info")
async def sync_account_info(request: dict):
    logger.info(f"Sync account info request received: {request}")

    try:
        """
        # Connect to Active Directory
        ad_domain = ADDomain(
            domain_name="your_domain",
            username="your_username",
            password="your_password"
        )

        user_id = request.get("user_id")
        authorizations = request.get("authorizations", [])

        # Check if user exists, if not create the user
        if not ad_domain.user_exists(user_id):
            ad_domain.create_user(user_id)
            logger.info(f"Created new user in AD: {user_id}")

        # Update user's authorizations (groups) in AD
        current_groups = set(ad_domain.get_user_groups(user_id))
        desired_groups = set(authorizations)

        # Add user to missing groups
        for group in desired_groups - current_groups:
            ad_domain.add_user_to_group(user_id, group)
            logger.info(f"Added user {user_id} to group {group}")

        # Remove user from groups not in desired list
        for group in current_groups - desired_groups:
            ad_domain.remove_user_from_group(user_id, group)
            logger.info(f"Removed user {user_id} from group {group}")
        """
        response = {
            "user_id": request.get("user_id"),
            "success": True
        }
        logger.info(f"Account info synchronized successfully: {response}")
        return response

    except Exception as e:
        logger.error(f"Error synchronizing account info: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: " + str(e))


###############################################################################
# Endpoint to change authorizations
###############################################################################


# Note about authorizations - get the list of authorizations for the user
# from active directory, and add what is missing, but also remove what is
# not in the list of authorizations provided.
@app.post("/v1/sync_authorizations")
async def sync_authorizations(request: dict):
    logger.info(f"Sync authorizations request received: {request}")

    # If we get a payload that does not have authorizations, then
    # we assume that we need to remove all authorizations for that user.

    try:
        """
        # Connect to Active Directory
        ad_domain = ADDomain(
            domain_name="your_domain",
            username="your_username",
            password="your_password"
        )

        user_id = request.get("user_id")
        desired_authorizations = set(request.get("authorizations", []))

        # Fetch current authorizations from AD
        current_authorizations = set(ad_domain.get_user_groups(user_id))

        # Determine authorizations to add and remove
        to_add = desired_authorizations - current_authorizations
        to_remove = current_authorizations - desired_authorizations

        # Update authorizations in AD
        for auth in to_add:
            ad_domain.add_user_to_group(user_id, auth)

        for auth in to_remove:
            ad_domain.remove_user_from_group(user_id, auth)

        response = {
            "user_id": user_id,
            "added": list(to_add),
            "removed": list(to_remove)
        }
        """
        response = {"user_id": request.get("user_id"), "added": [], "removed": []}
        logger.info(f"Authorizations synchronized successfully: {response}")
        return response
    except Exception as e:
        logger.error(f"Error synchronizing authorizations: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

# This endpoint is for enabling or disabling a user in AD
@app.post("/v1/set_member_enabled")
async def set_member_enabled(request: dict):
    logger.info(f"Set member enabled request received: {request}")

    try:
        # First let's get the username and enabled status
        username = request.get("username")
        enabled = request.get("enabled", True)
        
        # Now connect to AD
        sesion = ad.create_session()
        user = ad.get_user_by_username(sesion, username)
        ad.set_user_enabled_status(sesion, user, enabled)
        ad.close_session(sesion)
        
        
        response = {"username": request.get("username"), "enabled": request.get("enabled", True)}
        logger.info(f"User enabled status set successfully: {response}")
        return response
    except Exception as e:
        logger.error(f"Error setting user enabled status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error: " + str(e))