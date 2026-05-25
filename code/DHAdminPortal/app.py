import re
import uuid
import requests
import json
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, render_template, session, request, redirect, url_for, flash
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, CSRFError
import msal

# Our stuff
import dhservices
from dhs_logging import logger
import app_config
from config import config

### Dev mode flag — read from app_config so we only check the env var once
AUTH_MODE = app_config.AUTH_MODE
DEV_BANNER = app_config.DEV_BANNER

if AUTH_MODE == "dev":
    logger.info("AUTH_MODE=dev — B2C authentication bypassed, dev login enabled")

app = Flask(__name__)
app.config.from_object(app_config)
Session(app)
csrf = CSRFProtect(app)

from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logger.warning(f"CSRF validation failed: {e.description}")
    if request.is_json or request.content_type == 'application/json':
        return {"error": "CSRF token missing or invalid"}, 400
    flash('Your session has expired or this form submission was invalid. Please try again.', 'error')
    return redirect(request.referrer or url_for('index'))

###############################################################################
# Field validation rules for member update endpoints
###############################################################################

# Field-specific validation: field_name -> (regex_pattern, max_length, error_message)
FIELD_VALIDATORS = {
    "username": (r'^[a-zA-Z0-9_-]+$', 16, "Username can only contain letters, numbers, underscores, and hyphens (max 16 chars)"),
    "active_directory_username": (r'^[a-zA-Z0-9_-]+$', 16, "AD username can only contain letters, numbers, underscores, and hyphens (max 16 chars)"),
    "primary_email_address": (r'^[a-zA-Z0-9@._+\-]+$', None, "Email contains invalid characters"),
    "pronouns": (None, 50, "Pronouns must be 50 characters or fewer"),
    "nametag_subtitle": (None, 100, "Nametag subtitle must be 100 characters or fewer"),
    "first_name": (None, 100, "First name must be 100 characters or fewer"),
    "last_name": (None, 100, "Last name must be 100 characters or fewer"),
    "nickname": (None, 100, "Nickname must be 100 characters or fewer"),
    "phone_number": (r'^[0-9() \-\.+]+$', 20, "Phone number can only contain digits, spaces, and ()-.+"),
    "emergency_contact_phone": (r'^[0-9() \-\.+]+$', 20, "Emergency contact phone can only contain digits, spaces, and ()-.+"),
    "emergency_contact_name": (None, 100, "Emergency contact name must be 100 characters or fewer"),
    "discord_username": (None, 50, "Discord username must be 50 characters or fewer"),
    "discord_handle": (None, 50, "Discord handle must be 50 characters or fewer"),
    "theme_song_url": (r'^https://', 500, "Theme song URL must start with https:// and be 500 characters or fewer"),
    "birthday": (r'^\d{4}-\d{2}-\d{2}$', 10, "Birthday must be in YYYY-MM-DD format"),
    "id_check_date": (r'^\d{4}-\d{2}-\d{2}$', 10, "ID check date must be in YYYY-MM-DD format"),
    "id_check_by": (r'^[1-9]\d*$', 10, "Onboarder must be a valid member"),
}

ID_CHECK_ACTIVATION_PAST_DAYS = 7
ID_CHECK_ACTIVATION_FUTURE_DAYS = 1  # Allows up to 24h of clock skew

def validate_id_check_fields(data, *, activation: bool, access_token=None):
    """Apply ID-check-specific validation that doesn't fit the regex pattern.

    - id_check_date: must parse as a real calendar date (regex alone allows
      garbage like 2026-13-01 / Feb 30); when activation=True, must fall
      within the past 7 days through tomorrow (24h skew tolerance).
    - id_check_by: must resolve to an existing member via DHService when
      access_token is supplied. Skipped if the field is None or the caller
      didn't pass a token (preserves test-client behavior).

    Returns (data, error_message). error_message is None if valid.
    """
    if "id_check_date" in data and data["id_check_date"]:
        try:
            date_value = datetime.strptime(data["id_check_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None, "ID check date must be a valid date in YYYY-MM-DD format"

        if activation:
            today = datetime.now().date()
            floor = today - timedelta(days=ID_CHECK_ACTIVATION_PAST_DAYS)
            ceiling = today + timedelta(days=ID_CHECK_ACTIVATION_FUTURE_DAYS)
            if date_value < floor or date_value > ceiling:
                return None, (
                    f"ID check date must be between {floor.isoformat()} and {ceiling.isoformat()}"
                )

    if access_token and "id_check_by" in data and data["id_check_by"] is not None:
        # Resolve via DHService — None response means the member doesn't
        # exist, regardless of how the int slipped past the regex.
        try:
            existing = dhservices.resolve_member_display_name(access_token, int(data["id_check_by"]))
        except Exception as e:
            logger.warning(f"Could not verify id_check_by={data['id_check_by']}: {e}")
            return None, "Could not verify onboarder member"
        if existing is None:
            return None, "Onboarder member not found"

    return data, None

def validate_age_18_or_older(birthday_str):
    """Validate that a birthday string represents someone 18 years or older.
    Returns (is_valid, error_message)."""
    try:
        dob = datetime.strptime(birthday_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False, "Birthday must be a valid date in YYYY-MM-DD format"
    today = datetime.now().date()
    if dob.year < 1900 or dob > today:
        return False, "Please enter a valid date of birth"
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 18:
        return False, "Member must be 18 years or older"
    return True, None

def validate_update_data(data, tab_name):
    """Validate and sanitize incoming field data for a member update.

    Strips whitespace from all string values, converts empty strings to None,
    and validates fields that have rules defined in FIELD_VALIDATORS.

    Returns (sanitized_data, error_message). error_message is None if valid.
    """
    sanitized = {}
    for key, value in data.items():
        # Pass through non-string values and internal fields unchanged
        if key == "modified_by":
            sanitized[key] = value
            continue

        # Strip whitespace and convert empty strings to None
        if isinstance(value, str):
            value = value.strip() or None

        # Apply field-specific validation rules
        if value is not None and key in FIELD_VALIDATORS:
            pattern, max_len, error_msg = FIELD_VALIDATORS[key]
            str_value = str(value)
            if max_len and len(str_value) > max_len:
                return None, error_msg
            if pattern and not re.match(pattern, str_value):
                return None, error_msg

        sanitized[key] = value

    # Age validation: birthday must represent someone 18+
    if "birthday" in sanitized and sanitized["birthday"] is not None:
        is_valid, age_error = validate_age_18_or_older(sanitized["birthday"])
        if not is_valid:
            return None, age_error

    return sanitized, None

###############################################################################
# Health check endpoint
###############################################################################

@app.route("/health")
def health():
    return "OK", 200

@app.route("/version")
def version():
    return {"version": config["git"]["version"]}, 200

###############################################################################
# Flask routes for B2C flows, including login and logout
###############################################################################

@app.route("/anonymous")
def anonymous():
    logger.info("Anonymous route accessed")
    return "anonymous page"

@app.route("/")
def index():
    logger.info("Main route accessed")
    
    if not session.get("user"):
        if AUTH_MODE == "dev":
            return redirect(url_for("dev_login"))
        logger.info("No user logged in, building auth code flow")
        session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
        return render_template(
            "index.html", auth_url=session["flow"]["auth_uri"], version=msal.__version__
        )
    else:
        logger.info("User logged in, rendering index with user info")
        
        # Always fetch fresh user roles and permissions to ensure they're up-to-date.
        # Initialize member_id outside the try so the render below can pass `None`
        # to the template if DHService is unreachable, instead of UnboundLocalError.
        member_id = None
        try:
            # Get access token for DHService
            access_token = dhservices.get_access_token(
                dhservices.DH_CLIENT_ID,
                dhservices.DH_CLIENT_SECRET
            )
            
            # Get member ID from email
            user_email = session["user"].get("email") or session["user"].get("preferred_username")
            member_data = dhservices.get_member_id(access_token, user_email)
            member_id = member_data.get("member_id")
            
            if member_id:
                # Get member roles
                roles_data = dhservices.get_member_roles(access_token, str(member_id))
                
                # Extract role name and permissions
                if roles_data and "roles" in roles_data and len(roles_data["roles"]) > 0:
                    role_info = roles_data["roles"][0]  # Get first role
                    session["user_role"] = role_info.get("role_name", "Unknown")
                    session["user_permissions"] = role_info.get("permission", {})
                    logger.info(f"Loaded permissions for {user_email}: {session['user_permissions']}")
                else:
                    session["user_role"] = "No Role"
                    session["user_permissions"] = {}
            else:
                session["user_role"] = "Unknown"
                session["user_permissions"] = {}
                
        except Exception as e:
            logger.error(f"Error fetching user roles: {e}")
            session["user_role"] = "Error"
            session["user_permissions"] = {}
        
        return render_template(
            "index.html",
            user=session["user"],
            user_role=session.get("user_role", "Unknown"),
            user_permissions=session.get("user_permissions", {}),
            current_member_id=member_id,
            version=msal.__version__
        )

@app.route("/login")
def login():
    if AUTH_MODE == "dev":
        return redirect(url_for("dev_login"))
    print("Login route accessed")
    # Technically we could use empty list [] as scopes to do just sign in,
    # here we choose to also collect end user consent upfront
    session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
    return render_template(
        "login.html", auth_url=session["flow"]["auth_uri"], version=msal.__version__
    )

@app.route(app_config.REDIRECT_PATH)  # Its absolute URL must match your app's redirect_uri set in B2C
def authorized():
    logger.info("Authorized route accessed")
    try:
        cache = _load_cache()
        result = _build_msal_app(cache=cache).acquire_token_by_auth_code_flow(
            session.get("flow", {}), request.args
        )
        if "error" in result:
            return render_template("auth_error.html", result=result)
        
        user_claims = result.get("id_token_claims")
        
        # Check if user has roles before allowing login
        try:
            # Get access token for DHService
            access_token = dhservices.get_access_token(
                dhservices.DH_CLIENT_ID, 
                dhservices.DH_CLIENT_SECRET
            )
            
            # Get member ID from email
            user_email = user_claims.get("email") or user_claims.get("preferred_username")
            if not user_email:
                logger.error("No email found in user claims")
                return render_template("auth_error.html", result={
                    "error": "Authorization Failed",
                    "error_description": "Unable to verify your account. No email address found."
                })
            
            member_data = dhservices.get_member_id(access_token, user_email)
            member_id = member_data.get("member_id")
            
            if not member_id:
                logger.warning(f"No member_id found for email: {user_email}")
                return render_template("auth_error.html", result={
                    "error": "Authorization Failed",
                    "error_description": "You are not authorized to access this application. Your account is not registered in the system."
                })
            
            # Get member roles
            roles_data = dhservices.get_member_roles(access_token, str(member_id))
            
            # Check if user has any roles
            if not roles_data or "roles" not in roles_data or len(roles_data["roles"]) == 0:
                logger.warning(f"No roles assigned to member_id: {member_id}, email: {user_email}")
                return render_template("auth_error.html", result={
                    "error": "Authorization Failed",
                    "error_description": "You are not authorized to access this application. No administrative roles have been assigned to your account. Please contact an administrator for access."
                })
            
            # User has roles, allow login
            logger.info(f"User {user_email} authorized with roles: {roles_data['roles']}")
            session["user"] = user_claims
            _save_cache(cache)
            
            # Log login activity
            try:
                dhservices.log_user_activity(
                    access_token,
                    str(member_id),
                    {
                        "activity_details": {
                            "action": "login",
                            "email": user_email,
                            "roles": roles_data.get('roles', [])
                        }
                    }
                )
            except Exception as log_error:
                logger.error(f"Failed to log login activity: {log_error}")
            
        except Exception as e:
            logger.error(f"Error checking user roles during authorization: {e}")
            return render_template("auth_error.html", result={
                "error": "Authorization Error",
                "error_description": f"An error occurred while verifying your account: {str(e)}"
            })
            
    except ValueError:  # Usually caused by CSRF
        pass  # Simply ignore them
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    logger.info("Logout route accessed")
    
    # Log logout activity before clearing session
    if session.get("user"):
        try:
            access_token = dhservices.get_access_token(
                dhservices.DH_CLIENT_ID,
                dhservices.DH_CLIENT_SECRET
            )
            user_email = session["user"].get("email") or session["user"].get("preferred_username")
            if user_email:
                member_data = dhservices.get_member_id(access_token, user_email)
                member_id = member_data.get("member_id")
                if member_id:
                    dhservices.log_user_activity(
                        access_token,
                        str(member_id),
                        {
                            "activity_details": {
                                "action": "logout",
                                "email": user_email
                            }
                        }
                    )
        except Exception as log_error:
            logger.error(f"Failed to log logout activity: {log_error}")
    
    session.clear()  # Wipe out user and its token cache from session

    if AUTH_MODE == "dev":
        # Dev mode — just redirect to index, no B2C logout needed
        response = redirect(url_for("index"))
    else:
        response = redirect(  # Also logout from your tenant's web session
            app_config.AUTHORITY
            + "/oauth2/v2.0/logout"
            + "?post_logout_redirect_uri="
            + url_for("index", _external=True)
        )

    return response

@app.route("/graphcall")
def graphcall():
    logger.info("Graphcall route accessed")
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("login"))
    graph_data = requests.get(  # Use token to call downstream service
        app_config.ENDPOINT,
        headers={"Authorization": "Bearer " + token["access_token"]},
    ).json()
    return render_template("graph.html", result=graph_data)

def _load_cache():
    logger.info("Loading token cache")
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])
    return cache

def _save_cache(cache):
    logger.info("Saving token cache")
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()

def _build_msal_app(cache=None, authority=None):
    logger.info("Building MSAL app")
    return msal.ConfidentialClientApplication(
        app_config.CLIENT_ID,
        authority=authority or app_config.AUTHORITY,
        client_credential=app_config.CLIENT_SECRET,
        token_cache=cache,
    )

def _build_auth_code_flow(authority=None, scopes=None):
    logger.info("Building auth code flow")
    return _build_msal_app(authority=authority).initiate_auth_code_flow(
        scopes or [], redirect_uri=url_for("authorized", _external=True)
    )

def _get_token_from_cache(scope=None):
    logger.debug("Getting token from cache")
    cache = _load_cache()  # This web app maintains one cache per session
    cca = _build_msal_app(cache=cache)
    accounts = cca.get_accounts()
    if accounts:  # So all account(s) belong to the current signed-in user
        result = cca.acquire_token_silent(scope, account=accounts[0])
        _save_cache(cache)
        return result

app.jinja_env.globals.update(_build_auth_code_flow=_build_auth_code_flow)  # Used in template
app.jinja_env.globals.update(git_version=config.get("git", "version", fallback="unknown"))  # Used in footer
app.jinja_env.globals.update(now=datetime.now)  # Used in footer for dynamic year
app.jinja_env.globals.update(auth_mode=AUTH_MODE)  # Used in dev login routes
app.jinja_env.globals.update(dev_banner=DEV_BANNER)  # Used in dev banner

@app.context_processor
def inject_theme():
    """Inject admin_theme into all templates."""
    theme = session.get("admin_theme", "bubblegum")
    if theme not in ("bubblegum", "light", "dark", "midnight", "hacker"):
        theme = "bubblegum"
    return {"admin_theme": theme}


###############################################################################
# Permission checking decorator for admin API endpoints
###############################################################################

def requires_change_permission(tab_name):
    """Check that the logged-in user has 'change' permission for the given tab."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("user"):
                return {"error": "Not authenticated"}, 401
            permissions = session.get("user_permissions", {})
            change_perms = permissions.get("change", [])
            if "all" not in change_perms and tab_name not in change_perms:
                user_email = session["user"].get("email") or session["user"].get("preferred_username")
                logger.warning(
                    f"Permission denied: {user_email} attempted to change '{tab_name}'"
                )
                return {"error": "Permission denied"}, 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def requires_view_permission(tab_name):
    """Check that the logged-in user has 'view' or 'change' permission for the given tab."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("user"):
                return {"error": "Not authenticated"}, 401
            permissions = session.get("user_permissions", {})
            view_perms = permissions.get("view", [])
            change_perms = permissions.get("change", [])
            if ("all" not in view_perms and tab_name not in view_perms and
                    "all" not in change_perms and tab_name not in change_perms):
                user_email = session["user"].get("email") or session["user"].get("preferred_username")
                logger.warning(
                    f"Permission denied: {user_email} attempted to view '{tab_name}'"
                )
                return {"error": "Permission denied"}, 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


###############################################################################
# Dev mode login routes — only active when AUTH_MODE=dev
# These replace the B2C authentication flow with a simple user picker
# that lets developers quickly log in as preset seed-data users.
# Authorization (role/permission checks) still works normally.
###############################################################################

# Preset users for the dev login page. These match the seed data in
# pg/sql/seed_data.sql.example — don't change the IDs without updating the SQL.
ADMIN_DEV_USERS = [
    {"member_id": 1, "name": "Ada Lovelace", "email": "ada.lovelace@example.com", "role": "Administrator"},
    {"member_id": 3, "name": "Nikola Tesla", "email": "nikola.tesla@example.com", "role": "Authorizer"},
    {"member_id": 5, "name": "Grace Hopper", "email": "grace.hopper@example.com", "role": "Board"},
]

@app.route("/dev-login")
def dev_login():
    """Show the dev login page with preset user options"""
    if AUTH_MODE != "dev":
        return redirect(url_for("index"))
    return render_template("dev_login.html", preset_users=ADMIN_DEV_USERS)

@app.route("/dev-login/select", methods=["POST"])
def dev_login_select():
    """Handle dev login — authenticate via DHService API, set session"""
    if AUTH_MODE != "dev":
        return redirect(url_for("index"))

    member_id = request.form.get("member_id")
    if not member_id:
        return redirect(url_for("dev_login"))

    try:
        member_id = int(member_id)
    except (ValueError, TypeError):
        flash("Invalid member ID.", "error")
        return redirect(url_for("dev_login"))

    try:
        # Get DHService access token — same as the B2C callback does
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )

        # Get member identity to populate session
        identity = dhservices.get_member_identity(access_token, member_id)

        # Extract email from identity
        emails = identity.get("emails", [])
        email = emails[0]["email_address"] if emails else f"dev-user-{member_id}@example.com"

        # Verify they have roles (same check the B2C callback does)
        roles_data = dhservices.get_member_roles(access_token, member_id)
        if not roles_data or "roles" not in roles_data or len(roles_data["roles"]) == 0:
            return render_template("auth_error.html", result={
                "error": "Authorization Failed",
                "error_description": f"Member ID {member_id} has no admin roles assigned. "
                    "The admin portal requires a role (Administrator, Authorizer, or Board)."
            })

        # Build a user dict that looks like what B2C id_token_claims would give us
        session["user"] = {
            "name": f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip(),
            "email": email,
            "preferred_username": email,
            "dev_mode": True,
        }

        logger.info(f"Dev login: member_id={member_id}, email={email}")

        # Log login activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(member_id),
                {
                    "activity_details": {
                        "action": "dev_login",
                        "email": email,
                        "roles": roles_data.get("roles", [])
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log dev login activity: {log_error}")

    except Exception as e:
        logger.error(f"Dev login error: {e}")
        return render_template("auth_error.html", result={
            "error": "Dev Login Error",
            "error_description": f"Failed to authenticate with DHService: {str(e)}. "
                "Make sure the database is running and seed data is loaded."
        })

    return redirect(url_for("index"))


###############################################################################
# API routes to call DHService endpoints
###############################################################################

@app.route("/api/log_activity", methods=["POST"])
def api_log_activity():
    """Log user activity (tab selections, etc.)"""
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        # Get activity data from request
        activity_data = request.get_json()
        
        # Log the activity
        result = dhservices.log_user_activity(
            access_token,
            str(logged_in_member_id),
            {"activity_details": activity_data}
        )
        
        return result
    except Exception as e:
        logger.error(f"Error logging user activity: {e}")
        return {"error": str(e)}, 500

@app.route("/api/members")
@requires_view_permission("member.identity")
def api_members():

    query = request.args.get("query", "") or None
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    sort = request.args.get("sort", "date_added")
    order = request.args.get("order", "desc")

    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )

        result = dhservices.list_members(access_token, query, page, per_page, sort, order)

        # Log search activity only when an explicit search query is present
        if query:
            try:
                user_email = session["user"].get("email") or session["user"].get("preferred_username")
                member_data = dhservices.get_member_id(access_token, user_email)
                logged_in_member_id = member_data.get("member_id")
                dhservices.log_user_activity(
                    access_token,
                    str(logged_in_member_id),
                    {
                        "activity_details": {
                            "action": "search",
                            "query": query,
                            "results_count": result.get("total", 0)
                        }
                    }
                )
            except Exception as log_error:
                logger.error(f"Failed to log search activity: {log_error}")

        return result
    except Exception as e:
        logger.error(f"Error listing members: {e}")
        return {"error": str(e)}, 500

@app.route("/api/search")
@requires_view_permission("member.identity")
def api_search():
    
    query = request.args.get("query", "")
    if not query:
        return {"error": "Query parameter required"}, 400
    
    try:
        # Get access token for DHService    
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        
        # Get logged-in user's member ID for logging
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        # Search for members
        members = dhservices.search_members(access_token, query)
        
        # Log search activity
        try:
            # Handle both dict and list responses
            if isinstance(members, dict):
                results_count = len(members.get("members", []))
            elif isinstance(members, list):
                results_count = len(members)
            else:
                results_count = 0
            
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "search",
                        "query": query,
                        "results_count": results_count
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log search activity: {log_error}")
        
        return members
    except Exception as e:
        print(f"Error searching members: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/identity")
@requires_view_permission("member.identity")
def api_member_identity():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        # Get access token for DHService
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        
        # Get member identity
        identity = dhservices.get_member_identity(access_token, member_id)
        return identity
    except Exception as e:
        print(f"Error getting member identity: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/roles")
@requires_view_permission("member.roles")
def api_member_roles():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        # Get access token for DHService
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        
        # Get member roles
        roles = dhservices.get_member_roles(access_token, member_id)
        logger.info(f"Member roles for member_id {member_id}: {roles}")
        return roles
    except Exception as e:
        print(f"Error getting member roles: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/status")
@requires_view_permission("member.status")
def api_member_status():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        status = dhservices.get_member_status(access_token, member_id)
        return status
    except Exception as e:
        print(f"Error getting member status: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/forms")
@requires_view_permission("member.forms")
def api_member_forms():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401

    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400

    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        forms = dhservices.get_member_forms(access_token, member_id)
        return forms
    except Exception as e:
        logger.error(f"Error getting member forms: {e}")
        return {"error": str(e)}, 500

@app.route("/api/onboarder-search")
@requires_view_permission("member.forms")
def api_onboarder_search():
    """Typeahead search for the onboarder picker."""
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401

    query = request.args.get("query", "")
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    # Clamp to a sane band: 0 → no results (also: Postgres rejects negative
    # LIMIT with an error), 100 ceiling so a malicious or buggy caller can't
    # request the whole member table.
    limit = max(0, min(limit, 100))

    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.search_onboarder_candidates(access_token, query, limit)
    except Exception as e:
        logger.error(f"Error searching onboarder candidates: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/display-name")
@requires_view_permission("member.forms")
def api_member_display_name():
    """Resolve a member ID to identity name fields. Used to render the
    onboarder name from a stored `forms.id_check_by` value."""
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401

    raw = request.args.get("member_id", "")
    if not raw:
        return {"error": "member_id parameter required"}, 400
    try:
        member_id = int(raw)
    except (TypeError, ValueError):
        return {"error": "member_id must be an integer"}, 400

    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        name = dhservices.resolve_member_display_name(access_token, member_id)
        if name is None:
            return {"error": "Member not found"}, 404
        return name
    except Exception as e:
        logger.error(f"Error resolving member display name: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/connections")
@requires_view_permission("member.connections")
def api_member_connections():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        connections = dhservices.get_member_connections(access_token, member_id)
        return connections
    except Exception as e:
        print(f"Error getting member connections: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/extras")
@requires_view_permission("member.extras")
def api_member_extras():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        extras = dhservices.get_member_extras(access_token, member_id)
        # They may not have any extras, so return empty dict instead of null
        if extras is None:
            extras = {}
        return extras
    except Exception as e:
        print(f"Error getting member extras: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/authorizations")
@requires_view_permission("member.authorizations")
def api_member_authorizations():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        authorizations = dhservices.get_member_authorizations(access_token, member_id)
        if authorizations is None:
            # They may not have any authorizations, so return empty list instead of null
            authorizations = []
        return authorizations
    except Exception as e:
        print(f"Error getting member authorizations: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/notes")
@requires_view_permission("member.notes")
def api_member_notes():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        notes = dhservices.get_member_notes(access_token, member_id)
        return notes
    except Exception as e:
        print(f"Error getting member notes: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/entry")
@requires_view_permission("member.entry")
def api_member_entry():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        entry_logs = dhservices.get_member_entry_logs(access_token, member_id)
        return entry_logs
    except Exception as e:
        print(f"Error getting member entry logs: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/access")
@requires_view_permission("member.access")
def api_member_access():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        access = dhservices.get_member_access(access_token, member_id)
        if access is None:
            # They may not have any access records (e.g. new member)
            # so return empty list instead of null
            access = []
        return access
    except Exception as e:
        print(f"Error getting member access: {e}")
        return {"error": str(e)}, 500

@app.route("/api/authorizations/available")
def api_available_authorizations():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        available_auths = dhservices.get_available_authorizations(access_token)
        return available_auths
    except Exception as e:
        print(f"Error getting available authorizations: {e}")
        return {"error": str(e)}, 500

@app.route("/api/membership_levels/available")
def api_available_membership_levels():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401

    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        levels = dhservices.get_available_membership_levels(access_token)
        return levels
    except Exception as e:
        print(f"Error getting available membership levels: {e}")
        return {"error": str(e)}, 500

# POST endpoints for updating member data
@app.route("/api/member/identity", methods=["POST"])
@requires_change_permission("member.identity")
def api_update_member_identity():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data, error = validate_update_data(data, "identity")
        if error:
            return {"error": error}, 400
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_identity(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_identity",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member identity: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/status", methods=["POST"])
@requires_change_permission("member.status")
def api_update_member_status():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_status(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_status",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member status: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/roles", methods=["POST"])
@requires_change_permission("member.roles")
def api_update_member_roles():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_roles(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_roles",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member roles: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/extras", methods=["POST"])
@requires_change_permission("member.extras")
def api_update_member_extras():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_extras(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_extras",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member extras: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/authorizations", methods=["POST"])
@requires_change_permission("member.authorizations")
def api_update_member_authorizations():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_authorizations(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_authorizations",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member authorizations: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/notes", methods=["POST"])
@requires_change_permission("member.notes")
def api_update_member_notes():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_notes(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_notes",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member notes: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/access", methods=["POST"])
@requires_change_permission("member.access")
def api_update_member_access():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()

        # Validate RFID tags
        rfid_tags = data.get("rfid_tags", [])
        if not isinstance(rfid_tags, list):
            return {"error": "rfid_tags must be a list"}, 400
        for tag in rfid_tags:
            if not isinstance(tag, str) or not tag.isdigit() or len(tag) != 10:
                return {"error": f"Each RFID tag must be exactly 10 digits, got: {repr(tag)}"}, 400

        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_access(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_access",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member access: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/forms", methods=["POST"])
@requires_change_permission("member.forms")
def api_update_member_forms():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")

        data = request.get_json() or {}

        # The Onboard tab passes activation=true so the stricter date range
        # check applies. The Forms-tab path leaves it unset.
        activation = bool(data.pop("activation", False))

        sanitized, error = validate_update_data(data, "forms")
        if error:
            return {"error": error}, 400
        sanitized, error = validate_id_check_fields(sanitized, activation=activation, access_token=access_token)
        if error:
            return {"error": error}, 400

        # If id_check_by came through as a string (from JSON or the picker
        # hidden input), coerce to int now that it's passed validation.
        if "id_check_by" in sanitized and sanitized["id_check_by"] is not None:
            sanitized["id_check_by"] = int(sanitized["id_check_by"])

        sanitized["modified_by"] = logged_in_member_id
        result = dhservices.update_member_forms(access_token, member_id, sanitized)

        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_forms",
                        "target_member_id": member_id,
                        "fields_updated": [k for k in sanitized.keys() if k != "modified_by"]
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")

        return result
    except Exception as e:
        logger.error(f"Error updating member forms: {e}")
        return {"error": str(e)}, 500

@app.route("/api/member/connections", methods=["POST"])
@requires_change_permission("member.connections")
def api_update_member_connections():
    if not session.get("user"):
        return {"error": "Not authenticated"}, 401
    
    member_id = request.args.get("member_id", "")
    if not member_id:
        return {"error": "member_id parameter required"}, 400
    
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        # Get logged-in user's member ID
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        logged_in_member_id = member_data.get("member_id")
        
        data = request.get_json()
        data, error = validate_update_data(data, "connections")
        if error:
            return {"error": error}, 400
        data["modified_by"] = logged_in_member_id
        result = dhservices.update_member_connections(access_token, member_id, data)
        
        # Log update activity
        try:
            dhservices.log_user_activity(
                access_token,
                str(logged_in_member_id),
                {
                    "activity_details": {
                        "action": "update_connections",
                        "target_member_id": member_id,
                        "fields_updated": list(data.keys())
                    }
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log update activity: {log_error}")
        
        return result
    except Exception as e:
        logger.error(f"Error updating member connections: {e}")
        return {"error": str(e)}, 500

###############################################################################
# Space API routes (access logs, etc.)
###############################################################################

@app.route("/api/space/access_logs")
@requires_view_permission("space.access_logs")
def api_access_logs():
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if not start_date or not end_date:
        return {"error": "start_date and end_date required"}, 400

    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.get_access_logs(access_token, start_date, end_date)
    except Exception as e:
        logger.error(f"Error fetching access logs: {e}")
        return {"error": str(e)}, 500

###############################################################################
# Admin API routes (roles management, assign roles)
###############################################################################

@app.route("/api/admin/roles")
@requires_view_permission("systems.roles")
def api_get_roles():
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.get_all_roles(access_token)
    except Exception as e:
        logger.error(f"Error fetching roles: {e}")
        return {"error": str(e)}, 500

@app.route("/api/admin/roles", methods=["POST"])
@requires_change_permission("systems.roles")
def api_create_role():
    data = request.get_json()
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.create_role(access_token, data["name"], data["permission"])
    except Exception as e:
        logger.error(f"Error creating role: {e}")
        return {"error": str(e)}, 500

@app.route("/api/admin/roles", methods=["PUT"])
@requires_change_permission("systems.roles")
def api_update_role():
    data = request.get_json()
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.update_role(access_token, data["id"], data["name"], data["permission"])
    except Exception as e:
        logger.error(f"Error updating role: {e}")
        return {"error": str(e)}, 500

@app.route("/api/admin/assign_role", methods=["POST"])
@requires_change_permission("systems.assign_roles")
def api_assign_role():
    data = request.get_json()
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.assign_role_to_member(access_token, data["member_id"], data["role_id"])
    except Exception as e:
        logger.error(f"Error assigning role: {e}")
        return {"error": str(e)}, 500

@app.route("/api/admin/members_with_roles")
@requires_view_permission("systems.assign_roles")
def api_members_with_roles():
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.get_members_with_roles(access_token)
    except Exception as e:
        logger.error(f"Error fetching members with roles: {e}")
        return {"error": str(e)}, 500

@app.route("/api/admin/remove_role", methods=["POST"])
@requires_change_permission("systems.assign_roles")
def api_remove_role():
    data = request.get_json()
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        return dhservices.remove_role_from_member(access_token, data["member_id"])
    except Exception as e:
        logger.error(f"Error removing role: {e}")
        return {"error": str(e)}, 500


###############################################################################
# Equipment Module proxy routes
# Proxies equipment config and webhook-test to the DHEquipment service so
# DHAdmin can host the Equipment Module settings panel.
###############################################################################

def _equip_ctx():
    """Build member context dict from current session."""
    return {
        "member_id":   session.get("member_id"),
        "permissions": session.get("user_permissions", {}),
        "role":        session.get("user_role", ""),
    }


@app.route("/api/equipment/config/<key>", methods=["GET"])
@requires_view_permission("equipment.config")
def api_equip_get_config(key):
    ctx = _equip_ctx()
    try:
        result = dhservices.equip_get(f"/v1/equipment/config/{key}", **ctx)
        return result
    except Exception as e:
        logger.error(f"Error fetching equipment config {key}: {e}")
        return {"error": str(e)}, 500


@app.route("/api/equipment/config/<key>", methods=["PUT"])
@requires_change_permission("equipment.config")
def api_equip_set_config(key):
    ctx = _equip_ctx()
    body = request.get_json(silent=True) or {}
    try:
        result = dhservices.equip_put(f"/v1/equipment/config/{key}", body, **ctx)
        return result
    except Exception as e:
        logger.error(f"Error setting equipment config {key}: {e}")
        return {"error": str(e)}, 500


@app.route("/api/equipment/webhook-test", methods=["POST"])
@requires_change_permission("equipment.config")
def api_equip_webhook_test():
    """Send a test payload to a webhook URL server-side (avoids CORS)."""
    import hmac as _hmac, hashlib as _hashlib, json as _json
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()
    wh_type = body.get("type", "generic")
    secret = body.get("secret", "")
    discord_username = body.get("discord_username", "DH Equipment")
    discord_avatar = body.get("discord_avatar_url", "")
    discord_style = body.get("discord_style", {})

    if not url:
        return {"error": "No URL provided"}, 400

    ts = datetime.utcnow().isoformat() + "Z"
    test_payload = {"title": "Test Event", "status": "test", "event": "test"}

    try:
        import requests as _req
        if wh_type == "discord":
            title_prefix = discord_style.get("title_prefix", "").strip()
            embed_title = f"{title_prefix} Test Notification".strip() if title_prefix else "Test Notification"
            custom_color = discord_style.get("color", "").strip().lstrip("#")
            try:
                color = int(custom_color, 16) if custom_color else 0x5865F2
            except ValueError:
                color = 0x5865F2
            desc_template = discord_style.get("description_template", "").strip()
            description = desc_template.format_map({**test_payload, "event": "test"}) if desc_template \
                else "This is a test notification from Deep Harbor Equipment Management."
            footer_text = discord_style.get("footer", "").strip() or "Deep Harbor Equipment"
            content = discord_style.get("content", "").strip()
            send_body = {
                "username": discord_username or "DH Equipment",
                "embeds": [{
                    "title": embed_title,
                    "description": description,
                    "color": color,
                    "footer": {"text": footer_text},
                    "timestamp": ts,
                }],
            }
            if content:
                send_body["content"] = content
            if discord_avatar:
                send_body["avatar_url"] = discord_avatar
            resp = _req.post(url, json=send_body,
                             headers={"User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)"},
                             timeout=10)
        else:
            generic_payload = {
                "event": "test",
                "source": "dh-equipment",
                "message": "This is a test notification from Deep Harbor Equipment Management.",
                "timestamp": ts,
            }
            headers = {"Content-Type": "application/json"}
            if secret:
                sig = _hmac.new(secret.encode(), _json.dumps(generic_payload).encode(), _hashlib.sha256).hexdigest()
                headers["X-DH-Signature"] = f"sha256={sig}"
            resp = _req.post(url, json=generic_payload, headers=headers, timeout=10)

        return {"status": resp.status_code, "ok": resp.ok}, 200
    except Exception as e:
        logger.error(f"Webhook test error: {e}")
        return {"error": str(e)}, 500