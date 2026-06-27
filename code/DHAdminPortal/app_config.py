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
    # Dev mode — no B2C needed. Set placeholders so the rest of the app
    # doesn't crash on missing attributes. The actual auth flow will be
    # intercepted by the dev login routes in app.py.
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

###############################################################################
# Flask Secret Key & Session Security
###############################################################################

if AUTH_MODE == "dev":
    SECRET_KEY = config.get("flask", "secret_key", fallback="dev-secret-key-not-for-production")
else:
    SECRET_KEY = config.get("flask", "secret_key", fallback=None)
    if not SECRET_KEY:
        from dhs_logging import logger
        logger.error("SECRET_KEY is not set. Add [flask] secret_key to config.ini or set the DH_SECRET_KEY environment variable.")
        raise RuntimeError(
            "SECRET_KEY is not set. Add [flask] secret_key to config.ini "
            "or set the DH_SECRET_KEY environment variable."
        )

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
# Secure flag: on everywhere except dev (which serves plaintext http://localhost).
# AUTH_MODE is "dev" only in the docker-compose.dev.yml overlay; unset in prod.
SESSION_COOKIE_SECURE = AUTH_MODE != "dev"

###############################################################################
# Trusted Hosts (HOSTFIX-001: Host-header / open-redirect hardening)
###############################################################################
# Flask validates the inbound Host (and the X-Forwarded-Host that waitress /
# ProxyFix promote) against this allowlist and returns 400 on a mismatch, so a
# spoofed Host cannot poison url_for(_external=True) (the OAuth redirect_uri and
# post_logout_redirect_uri). Werkzeug strips the port before matching, so bare
# hostnames cover any port.
#
# Dev disables filtering entirely (None) so the multi-host dev setup (localhost
# plus the reverse-proxied edge) never dead-ends, mirroring SESSION_COOKIE_SECURE
# being off in dev. In prod the hosts come from DH_TRUSTED_HOSTS (root .env,
# comma-separated, multiple allowed); "localhost"/127.0.0.1 are unioned in
# automatically for the Docker /health curl. An unset DH_TRUSTED_HOSTS leaves
# validation off (current behavior) so a missing config never dead-ends the portal.
if AUTH_MODE == "dev":
    TRUSTED_HOSTS = None
else:
    _trusted_hosts_raw = os.environ.get("DH_TRUSTED_HOSTS", "")
    _trusted_hosts = [h.strip() for h in _trusted_hosts_raw.split(",") if h.strip()]
    TRUSTED_HOSTS = (["localhost", "127.0.0.1"] + _trusted_hosts) if _trusted_hosts else None
    if TRUSTED_HOSTS is None:
        from dhs_logging import logger
        logger.warning(
            "DH_TRUSTED_HOSTS is not set: Host-header validation is DISABLED "
            "(HOSTFIX-001). Set DH_TRUSTED_HOSTS to the portal's public "
            "hostname(s) in production."
        )
