import uuid
import requests
import json
from flask import Flask, render_template, session, request, redirect, url_for, make_response, flash
from flask_session import Session  
import msal
from datetime import datetime

# Our stuff
import dhservices
from dhs_logging import logger
from config import config
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

@app.route('/')
def index():
    """Landing page with login and signup options"""
    return render_template('landing.html')

@app.route('/signup')
def signup_start():
    """First step of signup - email entry"""
    # Clear any existing session data to prevent showing previous data from any login or signup attempts
    session.clear()
    return render_template('signup_email.html')

@app.route('/signup/check-email', methods=['POST'])
def signup_check_email():
    """Check if email exists in contacts and show signup form"""
    email = request.form.get('email')
    
    if not email:
        return render_template('signup_email.html', error='Please enter an email address')
    
    # Get access token for API calls using client credentials
    try:
        # Get access token for DHService
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )

        # Search for existing contact
        contact_data = dhservices.search_contacts_by_email(access_token, email)
        logger.debug(f"Contact search result for {email}: {contact_data}")
        
        contact_obj = None
        if contact_data and isinstance(contact_data, list) and len(contact_data) > 0:
            contact_obj = contact_data[0].get('contact')
        
        # Show form with contact and waiver info
        return render_template('signup_form.html', 
                                email=email, 
                                contact=contact_obj,
                                contact_found=contact_obj is not None)

    except Exception as e:
        logger.error(f"Error checking for existing contact: {str(e)}")
        # On error, show empty form
        return render_template('signup_form.html', email=email, contact_found=False)

@app.route('/signup/submit', methods=['POST'])
def signup_submit():
    """Handle signup form submission"""
    logger.debug("Handling signup form submission")
    
    email = request.form.get("email")
    waiver_signed_at = request.form.get("waiver_signed_at")
    waiver_signed = waiver_signed_at is not None and waiver_signed_at.strip() != ""
    
    # Piece together the data from the form submission
    identity_data = {
        "first_name": request.form.get("first_name"),
        "last_name": request.form.get("last_name"),
        "emails": [{"type": "primary", "email_address": email}],
        "nickname": request.form.get("preferred_name"),
        "active_directory_username": request.form.get("username"),
        "birthday": request.form.get("birthday")
    }
    connections_data = {
        "phone": request.form.get("phone"),
        "discord_handle": request.form.get("discord_handle")
    }
    status_data = {
        "waiver_signed": waiver_signed,
        "membership_level": "New Member",
        "membership_status": "Active",
        "member_since": datetime.now().strftime('%Y-%m-%d'),
        "renewal_date": None,        
    }
    forms_data = {
        "waiver_signed_at": waiver_signed_at or None
    }
    logger.debug(f"Waiver signed: {waiver_signed}, Waiver signed at: {waiver_signed_at}")
    logger.debug(f"Identity data to be sent for signup: {identity_data}")
    logger.debug(f"Connections data to be sent for signup: {connections_data}")
    logger.debug(f"Status data to be sent for signup: {status_data}")
    logger.debug(f"Forms data to be sent for signup: {forms_data}")
    
    try:
        # Get access token for DHService
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        logger.debug("Obtained access token for DHService")
    
        # First we need to get/create the member ID for the email provided
        member_id = dhservices.get_member_id(access_token, email).get("member_id")
        # If member_id is None, it means the member does not exist and needs to be created
        # otherwise the member exists with the email address and we gotta stop them from
        # signing up again
        if member_id is None:
            member_id = dhservices.add_member(access_token, identity_data).get("member_id")
            logger.info(f"Created new member with ID: {member_id}")
        else:
            flash('A member with this email already exists', 'error')
            return redirect(url_for('signup_start'))
        
        # Now we can send the connections data to the service to create 
        # the phone number and discord handle entries
        dhservices.update_member_connections(access_token, member_id, connections_data)
        logger.info(f"Updated member {member_id} with connections data")
        
        # Now, we set the status data for the new member
        dhservices.update_member_status(access_token, member_id, status_data)
        logger.info(f"Updated member {member_id} with status data")
        
        # Finally, we log the waiver form submission
        dhservices.update_member_forms(access_token, member_id, forms_data)
        logger.info(f"Logged waiver form submission for member {member_id}")
        
    except Exception as e:
        logger.error(f"Error creating new member: {str(e)}")
        flash('Error creating new member', 'error')
        return redirect(url_for('signup_start'))
    
    flash('Sign up successful! Please log in.', 'success')
    return redirect(url_for('login'))

@app.route("/login")
def login():
    logger.info("Login route accessed - redirecting to B2C")
    try:
        # Technically, we don't need to save the state because Flask session is stored on the server,
        # but we'll do it anyway because why not
        session["state"] = str(uuid.uuid4())
        # B2C expects "AUTH_CODE_FLOW" to be a Python dictionary in the Flask session.
        # Apparently, if we don't specify the cache, it will create a new one.
        auth_code_flow = _build_auth_code_flow(scopes=app_config.SCOPE)
        session["flow"] = auth_code_flow
        auth_uri = auth_code_flow["auth_uri"]
        logger.info(f"Redirecting to auth URI: {auth_uri}")
        # Redirect directly to B2C auth URL instead of showing login page
        return redirect(auth_uri)
    except Exception as e:
        logger.error(f"Error in login route: {str(e)}")
        flash('Error initiating login', 'error')
        return redirect(url_for('index'))

@app.route(app_config.REDIRECT_PATH)  # Its absolute URL must match your app's redirect_uri set in B2C
def authorized():
    logger.debug("Authorized route accessed")
    try:
        cache = _load_cache()
        result = _build_msal_app(cache=cache).acquire_token_by_auth_code_flow(
            session.get("flow", {}), request.args
        )
        if "error" in result:
            logger.error(f"Auth error: {result}")
            return render_template("auth_error.html", result=result)
        
        # Store user info in session
        session["user"] = result.get("id_token_claims")
        _save_cache(cache)
        
        # Get user email from token claims
        user_claims = session["user"]
        logger.info(f"User claims: {user_claims}")
        
        # Try different ways to get email
        email = None
        if "emails" in user_claims and user_claims["emails"]:
            email = user_claims["emails"][0]
        elif "email" in user_claims:
            email = user_claims["email"]
        elif "preferred_username" in user_claims:
            email = user_claims["preferred_username"]
        
        logger.info(f"Extracted email: {email}")
        
        if not email:
            logger.error(f"Could not extract email from claims: {user_claims}")
            flash('Could not retrieve email from login', 'error')
            return redirect(url_for('index'))
        
        # Cool, now we're logged in as a user and have their email
        logger.info(f"User {email} logged in successfully")
        # Get access token for API calls
        try:
            # Get access token for DHService
            access_token = dhservices.get_access_token(
                dhservices.DH_CLIENT_ID, 
                dhservices.DH_CLIENT_SECRET
            )
            logger.debug("Obtained access token for DHService")
            # Get member ID
            logger.info(f"Looking up member ID for email: {email}")
            member_data = dhservices.get_member_id(access_token, email)
            logger.info(f"Member data response: {member_data}")
            
            member_id = member_data.get('member_id')
            
            if not member_id:
                logger.error(f"No member_id found for email: {email}")
                flash('Member account not found', 'error')
                return redirect(url_for('index'))
            
            # Store in session
            session['access_token'] = access_token
            session['member_id'] = member_id
            session['email'] = email
            
            logger.info(f"Member {email} (ID: {member_id}) logged in successfully, redirecting to dashboard")
            return redirect(url_for('member_dashboard'))
            
        except Exception as e:
            logger.error(f"Error getting member data: {str(e)}", exc_info=True)
            flash('Error accessing member account', 'error')
            return redirect(url_for('index'))
            
    except ValueError as e:
        logger.error(f"CSRF or value error in authorized: {str(e)}", exc_info=True)
        flash('Authentication error, please try again', 'error')
    except Exception as e:
        logger.error(f"Unexpected error in authorized: {str(e)}", exc_info=True)
        flash('Login failed, please try again', 'error')
    
    return redirect(url_for("index"))

@app.route('/dashboard')
def member_dashboard():
    """Show member dashboard with identity and authorizations"""
    logger.info(f"Dashboard accessed - user in session: {session.get('user') is not None}, " +
                f"access_token in session: {session.get('access_token') is not None}, " +
                f"member_id in session: {session.get('member_id')}")
    
    if not session.get("user"):
        logger.warning("No user in session, redirecting to login")
        return redirect(url_for("login"))
    
    if 'access_token' not in session or 'member_id' not in session:
        logger.warning("Missing access_token or member_id in session, redirecting to login")
        return redirect(url_for('login'))
    
    access_token = session['access_token']
    user_email = session['email']
    
    try:
        logger.info(f"Fetching member data for user: {user_email}")
                
        # Get member information
        member_data = dhservices.get_member_id(access_token, user_email)
        member_id = member_data.get("member_id")
        
        member_info = dhservices.get_full_member_info(access_token, member_id)
        logger.info(f"Member info: {member_info}")
        
        # Split authorizations into computer and physical
        computer_auths = member_info.get('authorizations', {}).get('computer_authorizations', []) if isinstance(member_info, dict) else []
        physical_auths = member_info.get('authorizations', {}).get('physical_authorizations', []) if isinstance(member_info, dict) else []
        
        logger.info(f"Dashboard loaded successfully for member {member_id}")
        
        return render_template('member_dashboard.html',
                             identity=member_info.get('identity', {}) if isinstance(member_info, dict) else {},
                             authorizations_computer_authorizations=computer_auths,
                             authorizations_physical_authorizations=physical_auths,
                             status=member_info.get('status', {}) if isinstance(member_info, dict) else {},
                             extras=member_info.get('extras', {}) if isinstance(member_info, dict) else {},
                             forms=member_info.get('forms', []) if isinstance(member_info, dict) else {},
                             user=session.get('user'))
    except Exception as e:
        logger.error(f"Dashboard error: {str(e)}", exc_info=True)
        flash('Error loading dashboard', 'error')
        return redirect(url_for('login'))

@app.route("/logout")
def logout():
    logger.info("Logout route accessed")
    session.clear()  # Wipe out user and its token cache from session
    return redirect(  # Also logout from your tenant's web session
        app_config.AUTHORITY
        + "/oauth2/v2.0/logout"
        + "?post_logout_redirect_uri="
        + url_for("index", _external=True)
    )

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

@app.route('/api/check-username')
def check_username():
    """Check if a username is already taken"""
    username = request.args.get('username', '').strip()
    
    if not username:
        return {"error": "Username is required"}, 400
    
    try:
         # Get access token for DHService
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )
        is_taken = dhservices.is_username_taken(access_token, username)
        return {"is_taken": is_taken}
    except Exception as e:
        logger.error(f"Error checking username: {str(e)}")
        return {"error": "Error checking username"}, 500

@app.template_filter('format_date')
def format_date(date_string):
    """Format a date string to MM/DD/YYYY"""
    if not date_string:
        return ''
    try:
        # Try parsing common date formats
        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
            try:
                dt = datetime.strptime(date_string, fmt)
                return dt.strftime('%m/%d/%Y')
            except ValueError:
                continue
        # If no format matched, return the original string
        return date_string
    except:
        return date_string

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
# We want to show formatted dates in the dashboard
app.jinja_env.globals.update(format_date=format_date)  # Used in template