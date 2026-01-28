import os
from config import config

###############################################################################
# Azure AD B2C Configurations
###############################################################################
b2c_tenant = config["b2c"]["TENANT_NAME"]

signupsignin_user_flow = config["b2c"]["SIGNUPSIGNIN_USER_FLOW"]
editprofile_user_flow = config["b2c"]["EDITPROFILE_USER_FLOW"]
resetpassword_user_flow = config["b2c"]["RESETPASSWORD_USER_FLOW"]  # Note: Legacy setting.

authority_template = (
    "https://{tenant}.b2clogin.com/{tenant}.onmicrosoft.com/{user_flow}"
)

CLIENT_ID = config["b2c"]["CLIENT_ID"]  # Application (client) ID of app registration in Azure portal.
CLIENT_SECRET = config["b2c"]["CLIENT_SECRET"]  # Application secret.

AUTHORITY = authority_template.format(
    tenant=b2c_tenant, user_flow=signupsignin_user_flow
)
B2C_PROFILE_AUTHORITY = authority_template.format(
    tenant=b2c_tenant, user_flow=editprofile_user_flow
)
B2C_RESET_PASSWORD_AUTHORITY = authority_template.format(
    tenant=b2c_tenant, user_flow=resetpassword_user_flow
)

REDIRECT_PATH = "/getAToken"

# This is the API resource endpoint
ENDPOINT = config["b2c"]["ENDPOINT"]  # Application ID URI of app registration in Azure portal

# These are the scopes you've exposed in the web API app registration in the Azure portal
SCOPE = []

SESSION_TYPE = (
    "filesystem"  # Specifies the token cache should be stored in server-side session
)

