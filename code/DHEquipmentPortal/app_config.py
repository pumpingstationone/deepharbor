import os
from config import config

###############################################################################
# Auth Mode Configuration
###############################################################################

# AUTH_MODE is set by docker-compose.dev.yml. When it's "dev", we skip
# all B2C configuration and use a local dev login page instead.
AUTH_MODE = os.environ.get("AUTH_MODE", "").lower()
DEV_BANNER = os.environ.get("DEV_BANNER", "").lower() == "true"

###############################################################################
# Azure AD B2C Configurations
###############################################################################

if AUTH_MODE == "dev":
    CLIENT_ID = "dev-placeholder"
    CLIENT_SECRET = "dev-placeholder"
    AUTHORITY = "https://dev-placeholder.b2clogin.com"
    B2C_PROFILE_AUTHORITY = AUTHORITY
    B2C_RESET_PASSWORD_AUTHORITY = AUTHORITY
    REDIRECT_PATH = "/getAToken"
    ENDPOINT = ""
    SCOPE = []
else:
    b2c_tenant = config["b2c"]["TENANT_NAME"]

    signupsignin_user_flow = config["b2c"]["SIGNUPSIGNIN_USER_FLOW"]
    editprofile_user_flow = config["b2c"]["EDITPROFILE_USER_FLOW"]
    resetpassword_user_flow = config["b2c"]["RESETPASSWORD_USER_FLOW"]

    authority_template = (
        "https://{tenant}.b2clogin.com/{tenant}.onmicrosoft.com/{user_flow}"
    )

    CLIENT_ID = config["b2c"]["CLIENT_ID"]
    CLIENT_SECRET = config["b2c"]["CLIENT_SECRET"]

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
    ENDPOINT = config["b2c"]["ENDPOINT"]
    SCOPE = []

SESSION_TYPE = "filesystem"

###############################################################################
# Flask Secret Key & Session Security
###############################################################################

if AUTH_MODE == "dev":
    SECRET_KEY = config.get("flask", "secret_key", fallback="dev-secret-key-not-for-production")
else:
    SECRET_KEY = config.get("flask", "secret_key", fallback=None)
    if not SECRET_KEY:
        from dhs_logging import logger
        logger.error("SECRET_KEY is not set.")
        raise RuntimeError(
            "SECRET_KEY is not set. Add [flask] secret_key to config.ini "
            "or set the DH_SECRET_KEY environment variable."
        )

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True

# Allow uploads up to 260 MB (backend enforces 250 MB; extra headroom for multipart overhead)
MAX_CONTENT_LENGTH = 260 * 1024 * 1024
