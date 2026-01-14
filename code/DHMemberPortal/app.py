import uuid
import requests
import json
from flask import Flask, render_template, session, request, redirect, url_for, make_response
from flask_session import Session  
import msal

# Our stuff
import dhservices
from dhs_logging import logger
import app_config

app = Flask(__name__)
app.config.from_object(app_config)
Session(app)

from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

###############################################################################
# Flask routes for B2C flows, including login and logout
###############################################################################

@app.route("/anonymous")
def anonymous():
    logger.info("Anonymous route accessed")
    return "anonymous page"

@app.route("/")
def index():
    logger.info("Index route accessed")
    # if not session.get("user"):
    #    return redirect(url_for("login"))
    if not session.get("user"):
        logger.info("No user logged in, building auth code flow")
        session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
        return render_template(
            "index.html", auth_url=session["flow"]["auth_uri"], version=msal.__version__
        )
    else:
        logger.info("User logged in, rendering index with user info")
        
        # Always fetch fresh user roles and permissions to ensure they're up-to-date
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
        
        response = make_response(render_template(
            "index.html", 
            user=session["user"], 
            user_role=session.get("user_role", "Unknown"),
            version=msal.__version__
        ))
        
        # Set permissions cookie
        response.set_cookie(
            "user_permissions", 
            json.dumps(session.get("user_permissions", {})),
            httponly=False,  # Allow JavaScript access
            samesite="Lax"
        )
        
        return response

@app.route("/login")
def login():
    print("Login route accessed")
    # Technically we could use empty list [] as scopes to do just sign in,
    # here we choose to also collect end user consent upfront
    session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
    return render_template(
        "login.html", auth_url=session["flow"]["auth_uri"], version=msal.__version__
    )

@app.route(app_config.REDIRECT_PATH)  # Its absolute URL must match your app's redirect_uri set in AAD
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
    response = redirect(  # Also logout from your tenant's web session
        app_config.AUTHORITY
        + "/oauth2/v2.0/logout"
        + "?post_logout_redirect_uri="
        + url_for("index", _external=True)
    )
    # Clear permissions cookie on logout
    response.set_cookie("user_permissions", "", expires=0)
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
    print("Getting token from cache")
    cache = _load_cache()  # This web app maintains one cache per session
    cca = _build_msal_app(cache=cache)
    accounts = cca.get_accounts()
    if accounts:  # So all account(s) belong to the current signed-in user
        result = cca.acquire_token_silent(scope, account=accounts[0])
        _save_cache(cache)
        return result

app.jinja_env.globals.update(_build_auth_code_flow=_build_auth_code_flow)  # Used in template


###############################################################################
# API routes to call DHService endpoints
###############################################################################

