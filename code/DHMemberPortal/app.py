import uuid
import requests
import json
from flask import Flask, render_template, session, request, redirect, url_for, make_response, flash
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, CSRFError
import msal
from datetime import datetime

# Our stuff
import dhservices
from dhs_logging import logger
from config import config
import app_config

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
    flash('Your session has expired or this form submission was invalid. Please try again.', 'error')
    return redirect(request.referrer or url_for('index'))

### Fields updatable from dashboard forms, grouped by JSONB column.
### Only fields present in the form submission are updated — partial
### forms won't wipe fields they don't include.
### To add a new field, just add its name to the relevant list.
UPDATABLE_FIELDS = {
    "identity": ["first_name", "last_name", "nickname", "pronouns", "nametag_subtitle", "theme_song_url", "theme_song_duration"],
}

def apply_form_fields(form, data_dict, field_list):
    """Update data_dict with form values only for fields present in the submission."""
    for field in field_list:
        if field in form:
            data_dict[field] = form[field].strip() or None

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

@app.route('/')
def index():
    """Landing page with login and signup options"""
    if session.get("user"):
        return redirect(url_for("member_dashboard"))
    if AUTH_MODE == "dev":
        return render_template('dev_login.html', preset_users=MEMBER_DEV_USERS)
    return render_template('landing.html')

@app.route('/signup')
def signup_start():
    """First step of signup - email entry"""
    # Drop only the signup-scoped session key. Don't session.clear() — that
    # logs out any signed-in user who visits /signup (weaponizable as a
    # logout link, GET so no CSRF) and wipes the flash queue, so error
    # redirects from signup_submit lose their flash message before render.
    session.pop('signup_email', None)
    return render_template('signup_email.html')

@app.route('/signup/check-email', methods=['POST'])
def signup_check_email():
    """Check if email exists in contacts and show signup form"""
    email = request.form.get('email')
    
    if not email:
        return render_template('signup_email.html', error='Please enter an email address')
    
    session["signup_email"] = email

    # Get access token for API calls using client credentials
    try:
        # Get access token for DHService
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, 
            dhservices.DH_CLIENT_SECRET
        )

        # If a member already exists for this email, send them to SSO login
        member_data = dhservices.get_member_id(access_token, email)
        if member_data and member_data.get("member_id"):
            flash('An account already exists for this email. Please sign in.', 'info')
            return redirect(url_for('login'))

        # Search for existing contact
        contact_data = dhservices.search_contacts_by_email(access_token, email)
        logger.debug(f"Contact search result for {email}: {contact_data}")
        
        contact_obj = None
        if contact_data and isinstance(contact_data, list) and len(contact_data) > 0:
            contact_obj = contact_data[0].get('contact')

        # Per Sky on 2/12/26: We do not want to auto-populate the form
        # with the contact data as it could be a privacy concern. What
        # we will do is a new method where when they sign up with an email,
        # we will send them a link to the signup form where we can validate
        # that the email they entered is actually theirs by including a 
        # token in the link that they have to click on to access the form. 
        # That way, we can be sure that the person filling out the form has 
        # access to the email they entered, without actually showing them 
        # any of the contact data we have on file for that email. For now, 
        # we'll just show the empty form.
        contact_obj = None
        
        # Show form with contact and waiver info
        return render_template('signup_form.html', 
                                email=email, 
                                contact=contact_obj,
                                contact_found=contact_obj is not None)

    except Exception as e:
        logger.error(f"Error checking for existing contact: {str(e)}")
        # On error, show empty form
        return render_template('signup_form.html', email=email, contact_found=False)

@app.route('/signup/payment')
def signup_payment():
    """Show payment step with Stripe pricing table"""
    email = request.args.get('email') or session.get('signup_email')
    return render_template('signup_payment.html', email=email)

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
        "birthday": request.form.get("birthday"),
        "pronouns": request.form.get("pronouns")
    }
    connections_data = {
        "phone": request.form.get("phone"),
        "discord_handle": request.form.get("discord_handle")
    }
    status_data = {
        "waiver_signed": waiver_signed,
        "membership_level": "New Member",
        "membership_status": "pending", # They're pending until an admin approves it
        "member_since": datetime.now().strftime('%Y-%m-%d'),
        "renewal_date": None,        
    }
    
    # We want to pre-create some fields in the forms for
    # making it easier for the admins to review the new member's information 
    # and track their progress through the onboarding steps.
    forms_data = {
        "waiver_signed_at": waiver_signed_at or None,
        "id_check_1": "",
        "id_check_2": "",
        "terms_of_use_accepted": False,
        "orientation_completed_date": "",
        "essentials_forms_completed_date": "",
        "is_21_or_older": False,
    }
    notes_data = {
        "note": f"New signup with email {email}. Waiver signed: {waiver_signed}, Waiver signed at: {waiver_signed_at}",
        "from": "Member Portal Signup",
        "timestamp": datetime.now().isoformat()
    }
    # We are adding the RFID tags in the access data because we want them 
    # to be able to enter it in the signup form and have it show up in their 
    # profile right away instead of having to go into the dashboard and add 
    # it after the fact. This is because the RFID tag is required for them 
    # to be able to access the space, so it's better to have it in there 
    # from the start. We can always update it later if they get a new tag or something.
    access_data = {
        "rfid_tags": []
    }
    authorizations_data = {
        "computer_authorizations": [],
        "authorizations": []
    }
    extras_data = {
        "storage_area": None,        
    }
    
    logger.debug(f"Waiver signed: {waiver_signed}, Waiver signed at: {waiver_signed_at}")
    logger.debug(f"Identity data to be sent for signup: {identity_data}")
    logger.debug(f"Connections data to be sent for signup: {connections_data}")
    logger.debug(f"Status data to be sent for signup: {status_data}")
    logger.debug(f"Forms data to be sent for signup: {forms_data}")
    logger.debug(f"Notes data to be sent for signup: {notes_data}")
    logger.debug(f"Access data to be sent for signup: {access_data}")
    logger.debug(f"Authorizations data to be sent for signup: {authorizations_data}")
    logger.debug(f"Extras data to be sent for signup: {extras_data}")
    # The member-row creation (add_member) is the only step that MUST succeed
    # before we can hand the user off to Stripe. The scaffolding writes below
    # are best-effort: any one failing leaves a half-populated row that admin
    # tooling can address later, but the user still gets a Stripe checkout.
    # See #283.
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )
        logger.debug("Obtained access token for DHService")

        # If the email is already taken, bail before creating anything.
        existing_member_id = dhservices.get_member_id(access_token, email).get("member_id")
        if existing_member_id is not None:
            flash('A member with this email already exists', 'error')
            return redirect(url_for('signup_start'))

        # Server-side username uniqueness gate. /api/check-username is only
        # the AJAX UX hint — without this, the form happily creates a second
        # row with a duplicate active_directory_username, which collides in
        # AD/B2C downstream. Case-insensitive (matches is_username_available
        # in DHService, PR #252). Skip when no username was provided; the
        # broader required-field enforcement is tracked separately.
        username = (request.form.get("username") or "").strip()
        if username and dhservices.is_username_taken(access_token, username):
            flash('That username is already taken. Please choose another.', 'error')
            return redirect(url_for('signup_start'))

        member_id = dhservices.add_member(access_token, identity_data).get("member_id")
    except Exception as e:
        logger.error(f"Error creating new member: {str(e)}")
        flash('Error creating new member', 'error')
        return redirect(url_for('signup_start'))

    # DHService returns 200 with `member_id: null` on internal INSERT failure
    # (see add_update_identity in DHService/db.py). Guard explicitly so we
    # don't proceed with a null id into the scaffolding loop.
    if not member_id:
        logger.error(f"Signup add_member returned no member_id for email={email}")
        flash('Error creating new member', 'error')
        return redirect(url_for('signup_start'))

    logger.info(f"Created new member with ID: {member_id}")

    # Best-effort scaffolding initialization. We pre-populate these JSONB
    # columns so admin tooling sees a complete record on first pass instead of
    # nulls. Any single failure is logged and skipped — we still proceed to
    # Stripe, and ST2DH will fill in stripe_product_id on the status row when
    # payment lands. Admin can backfill any remaining blanks.
    scaffolding_steps = [
        ("connections",    dhservices.update_member_connections,    connections_data),
        ("status",         dhservices.update_member_status,         status_data),
        ("forms",          dhservices.update_member_forms,          forms_data),
        ("notes",          dhservices.update_member_notes,          notes_data),
        ("access",         dhservices.update_member_access,         access_data),
        ("authorizations", dhservices.update_member_authorizations, authorizations_data),
        ("extras",         dhservices.update_member_extras,         extras_data),
    ]
    for label, fn, payload in scaffolding_steps:
        try:
            fn(access_token, member_id, payload)
            logger.info(f"Signup member {member_id}: {label} initialized")
        except Exception as e:
            logger.error(
                f"Signup member {member_id}: {label} init failed (continuing): {str(e)}"
            )

    flash('Sign up successful! Please complete payment.', 'success')
    return redirect(url_for('signup_payment', email=email))

@app.route("/login")
def login():
    if AUTH_MODE == "dev":
        return redirect(url_for("index"))
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

            # Stash membership_status so the banned-member gate can fire on the
            # very first post-login request, not just after the first dashboard hit.
            try:
                full_info = dhservices.get_full_member_info(access_token, member_id) or {}
                session['membership_status'] = ((full_info.get('status') or {}).get('membership_status') or '').lower()
            except Exception as e:
                logger.warning(f"Could not fetch status at B2C login for member_id={member_id}: {e}")
                session['membership_status'] = ''

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

def _get_authenticated_member_info():
    """Shared helper for dashboard pages. Returns (member_info, error_redirect).
    If error_redirect is not None, the caller should return it."""
    if not session.get("user"):
        logger.warning("No user in session, redirecting to login")
        return None, redirect(url_for("index") if AUTH_MODE == "dev" else url_for("login"))

    if 'access_token' not in session or 'member_id' not in session:
        logger.warning("Missing access_token or member_id in session, redirecting to login")
        return None, redirect(url_for("index") if AUTH_MODE == "dev" else url_for("login"))

    access_token = session['access_token']
    member_id = session['member_id']

    try:
        logger.info(f"Fetching member data for member {member_id}")
        member_info = dhservices.get_full_member_info(access_token, member_id)
        # Refresh cached membership_status so the before_request gate catches
        # mid-session admin status flips (e.g. active → banned) on the next page.
        if isinstance(member_info, dict):
            session['membership_status'] = ((member_info.get('status') or {}).get('membership_status') or '').lower()
        return member_info, None
    except Exception as e:
        logger.error(f"Error fetching member data: {str(e)}", exc_info=True)
        flash('Error loading member data', 'error')
        return None, redirect(url_for('login'))


# Endpoints reachable by a banned member. Everything else redirects to the
# locked page. 'static' is Flask's auto-registered static-file endpoint —
# without it, the locked page's CSS/JS/images would also bounce.
_ALLOWED_ENDPOINTS_FOR_BANNED = {
    'health', 'version', 'anonymous',
    'logout', 'member_locked', 'static',
}


@app.before_request
def _gate_banned_members():
    if not session.get('user'):
        return None
    if request.endpoint in _ALLOWED_ENDPOINTS_FOR_BANNED:
        return None
    if (session.get('membership_status') or '').lower() == 'banned':
        return redirect(url_for('member_locked'))
    return None


@app.route('/dashboard/locked')
def member_locked():
    """Terminal-status landing page for banned members. Non-banned users
    are redirected away; anonymous users are sent to the login page."""
    if not session.get('user'):
        return redirect(url_for('index'))
    if (session.get('membership_status') or '').lower() != 'banned':
        return redirect(url_for('member_dashboard'))
    return render_template('dashboard_locked.html', user=session.get('user'))


@app.route('/dashboard')
def member_dashboard():
    """Show member dashboard menu"""
    member_info, error = _get_authenticated_member_info()
    if error:
        return error

    return render_template('member_dashboard.html',
                         status=member_info.get('status', {}) if isinstance(member_info, dict) else {},
                         user=session.get('user'))

@app.route('/dashboard/profile')
def member_profile():
    """Show member profile - name, nickname, email, username"""
    member_info, error = _get_authenticated_member_info()
    if error:
        return error

    return render_template('dashboard_profile.html',
                         identity=member_info.get('identity', {}) if isinstance(member_info, dict) else {},
                         status=member_info.get('status', {}) if isinstance(member_info, dict) else {},
                         access=member_info.get('access', {}) if isinstance(member_info, dict) else {},
                         user=session.get('user'))

@app.route('/dashboard/keys')
def member_keys():
    """Show member keys - RFID tags, future Doorbot"""
    member_info, error = _get_authenticated_member_info()
    if error:
        return error

    access = member_info.get('access', {}) if isinstance(member_info, dict) else {}

    # Pad RFID tags with leading zeros to 10 digits
    if access and 'rfid_tags' in access and access['rfid_tags']:
        if isinstance(access['rfid_tags'], list):
            access['rfid_tags'] = [tag.zfill(10) for tag in access['rfid_tags'] if isinstance(tag, str)]
        elif isinstance(access['rfid_tags'], str):
            access['rfid_tags'] = ','.join(tag.strip().zfill(10) for tag in access['rfid_tags'].split(',') if tag.strip())

    status = member_info.get('status', {}) if isinstance(member_info, dict) else {}
    keys_locked = (status.get('membership_status') or '').lower() != 'active'

    return render_template('dashboard_keys.html',
                         access=access,
                         identity=member_info.get('identity', {}) if isinstance(member_info, dict) else {},
                         status=status,
                         keys_locked=keys_locked,
                         user=session.get('user'))

@app.route('/dashboard/auths')
def member_auths():
    """Show member authorizations"""
    member_info, error = _get_authenticated_member_info()
    if error:
        return error

    computer_auths = member_info.get('authorizations', {}).get('computer_authorizations', []) if isinstance(member_info, dict) else []
    physical_auths = member_info.get('authorizations', {}).get('physical_authorizations', []) if isinstance(member_info, dict) else []

    return render_template('dashboard_auths.html',
                         computer_auths=computer_auths,
                         physical_auths=physical_auths,
                         status=member_info.get('status', {}) if isinstance(member_info, dict) else {},
                         user=session.get('user'))

@app.route('/dashboard/storage')
def member_storage():
    """Show storage, misc info, and forms data"""
    member_info, error = _get_authenticated_member_info()
    if error:
        return error

    forms = member_info.get('forms', {}) if isinstance(member_info, dict) else {}

    # Resolve the onboarder's display name from forms.id_check_by so the
    # template can render "ID verified on <date> by <name>" without exposing
    # raw member IDs. Failures are non-fatal — the line just falls back to
    # showing the ID.
    if forms.get('id_check_by'):
        try:
            access_token = session.get('access_token')
            if access_token:
                onboarder = dhservices.resolve_member_display_name(access_token, forms['id_check_by'])
                if onboarder:
                    parts = [onboarder.get('first_name'), onboarder.get('last_name')]
                    full_name = ' '.join(p for p in parts if p).strip()
                    forms['id_check_by_name'] = full_name or onboarder.get('username')
        except Exception as e:
            logger.warning(f"Could not resolve onboarder name for member_id={forms.get('id_check_by')}: {e}")

    return render_template('dashboard_info_storage.html',
                         extras=member_info.get('extras', {}) if isinstance(member_info, dict) else {},
                         forms=forms,
                         status=member_info.get('status', {}) if isinstance(member_info, dict) else {},
                         identity=member_info.get('identity', {}) if isinstance(member_info, dict) else {},
                         user=session.get('user'))

@app.route('/dashboard/floof')
def member_floof():
    """Show fun stuff page"""
    member_info, error = _get_authenticated_member_info()
    if error:
        return error

    return render_template('dashboard_floof.html',
                         identity=member_info.get('identity', {}) if isinstance(member_info, dict) else {},
                         status=member_info.get('status', {}) if isinstance(member_info, dict) else {},
                         user=session.get('user'))

@app.route('/dashboard/update-profile', methods=['POST'])
def member_update_profile():
    """Update member profile fields from dashboard"""
    if not session.get("user"):
        flash('Please log in to update your profile', 'error')
        return redirect(url_for('login'))

    if 'access_token' not in session or 'member_id' not in session:
        flash('Session expired, please log in again', 'error')
        return redirect(url_for('login'))

    access_token = session['access_token']
    member_id = session['member_id']
    user_email = session.get('email')

    # Fetch raw identity JSONB directly (not v_member_info via get_full_member_info)
    # so fields like birthday that aren't surfaced by the view are preserved when
    # we round-trip through the save.
    try:
        identity_data = dhservices.get_member_identity(access_token, member_id) or {}
        if not isinstance(identity_data, dict):
            identity_data = {}
    except Exception as e:
        logger.error(f"Error fetching identity for update: {str(e)}", exc_info=True)
        identity_data = {}

    # Save original identity before applying form fields so we can
    # skip the update if nothing actually changed — avoids creating
    # a spurious member_changes row that delays access change processing
    original_identity = dict(identity_data)

    apply_form_fields(request.form, identity_data, UPDATABLE_FIELDS["identity"])

    if not identity_data.get("emails") and user_email:
        identity_data["emails"] = [{"type": "primary", "email_address": user_email}]

    # Only process RFID tags if the field is in the form
    rfid_tags_raw = request.form.get('rfid_tags', '').strip() if 'rfid_tags' in request.form else None
    rfid_tags = [tag.strip() for tag in rfid_tags_raw.split(',') if tag.strip()] if rfid_tags_raw is not None else []
    access_data = {"rfid_tags": rfid_tags}

    # Validate RFID tags: must be exactly 10 numeric digits
    for tag in rfid_tags:
        if not tag.isdigit() or len(tag) != 10:
            flash('Each card or fob number must be exactly 10 digits.', 'error')
            source_page = request.form.get('source_page', 'profile')
            if source_page == 'keys':
                return redirect(url_for('member_keys'))
            return redirect(url_for('member_profile'))

    # Determine source page for redirect
    source_page = request.form.get('source_page', 'profile')

    # Server-side gate: RFID writes are only allowed for members with active
    # status. The UI disables the keys form for non-active members, but the
    # backend also enforces this so a hand-crafted POST can't sneak through.
    # Identity edits remain allowed for any status.
    if 'rfid_tags' in request.form:
        try:
            current_member_info = dhservices.get_full_member_info(access_token, member_id) or {}
            current_status = (current_member_info.get('status') or {}).get('membership_status') or ''
        except Exception as e:
            logger.error(f"Error fetching member status for RFID gate: {str(e)}", exc_info=True)
            current_status = ''
        if current_status.lower() != 'active':
            logger.warning(
                f"Refused RFID update for member_id={member_id} with status={current_status!r}"
            )
            flash("Your membership isn't active — key changes can't be saved.", 'error')
            if source_page == 'keys':
                return redirect(url_for('member_keys'))
            return redirect(url_for('member_profile'))

    try:
        if identity_data != original_identity:
            dhservices.update_member_identity(access_token, member_id, identity_data)
        if 'rfid_tags' in request.form:
            dhservices.update_member_access(access_token, member_id, access_data)
        flash('Profile updated successfully', 'success')
        if source_page == 'keys':
            flash('Remember to test your new keys before leaving the building, hearing the key reader beep does not mean the key works. Ask for help so you don\'t get locked out.', 'warning')
    except Exception as e:
        logger.error(f"Error updating member profile: {str(e)}", exc_info=True)
        flash('Error updating profile', 'error')
    if source_page == 'keys':
        return redirect(url_for('member_keys'))
    if source_page == 'floof':
        return redirect(url_for('member_floof'))
    return redirect(url_for('member_profile'))

@app.route("/logout")
def logout():
    logger.info("Logout route accessed")
    session.clear()  # Wipe out user and its token cache from session

    if AUTH_MODE == "dev":
        # Dev mode — just redirect to index, no B2C logout needed
        return redirect(url_for("index"))

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
        timeout=10,
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
    logger.debug("Getting token from cache")
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
app.jinja_env.globals.update(git_version=config.get("git", "version", fallback="unknown"))  # Used in footer
app.jinja_env.globals.update(now=datetime.now)  # Used in footer for dynamic year
app.jinja_env.globals.update(auth_mode=AUTH_MODE)  # Used in dev login routes
app.jinja_env.globals.update(dev_banner=DEV_BANNER)  # Used in dev banner


###############################################################################
# Dev mode login routes — only active when AUTH_MODE=dev
# These replace the B2C authentication flow with a simple user picker
# that lets developers quickly log in as preset seed-data users.
###############################################################################

# Preset users for the dev login page. These match the seed data in
# pg/sql/seed_data.sql.example — don't change the IDs without updating the SQL.
MEMBER_DEV_USERS = [
    {"member_id": 8, "name": "Katherine Johnson", "email": "katherine.johnson@example.com", "description": "Active member with full data"},
    {"member_id": 9, "name": "Dorothy Vaughan", "email": "dorothy.vaughan@example.com", "description": "Brand new member, pending / minimal data"},
    {"member_id": 10, "name": "Charles Babbage", "email": "charles.babbage@example.com", "description": "Suspended member"},
    {"member_id": 11, "name": "Nikola Tesla", "email": "nikola.tesla@example.com", "description": "Banned member"},
]

@app.route("/dev-login/select", methods=["POST"])
def dev_login_select():
    """Handle dev login — authenticate via DHService API, set session"""
    if AUTH_MODE != "dev":
        return redirect(url_for("index"))

    member_id = request.form.get("member_id")
    if not member_id:
        return redirect(url_for("index"))

    try:
        member_id = int(member_id)
    except (ValueError, TypeError):
        flash("Invalid member ID.", "error")
        return redirect(url_for("index"))

    try:
        # Get DHService access token
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID,
            dhservices.DH_CLIENT_SECRET
        )

        # Get member identity to populate session
        identity = dhservices.get_member_identity(access_token, member_id)

        # Extract email from identity
        emails = identity.get("emails", [])
        email = emails[0]["email_address"] if emails else f"dev-user-{member_id}@example.com"

        # Set session variables to match what the B2C authorized() callback sets
        session["user"] = {
            "name": f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip(),
            "email": email,
            "preferred_username": email,
            "dev_mode": True,
        }
        session["access_token"] = access_token
        session["member_id"] = member_id
        session["email"] = email

        # Stash membership_status so the banned-member gate can fire on the
        # very first post-login request, not just after the first dashboard hit.
        try:
            full_info = dhservices.get_full_member_info(access_token, member_id) or {}
            session['membership_status'] = ((full_info.get('status') or {}).get('membership_status') or '').lower()
        except Exception as e:
            logger.warning(f"Could not fetch status at dev login for member_id={member_id}: {e}")
            session['membership_status'] = ''

        logger.info(f"Dev login: member_id={member_id}, email={email}")

    except Exception as e:
        logger.error(f"Dev login error: {e}")
        flash(f"Dev login failed: {str(e)}. Make sure the database is running and seed data is loaded.", "error")
        return redirect(url_for("index"))

    return redirect(url_for("member_dashboard"))


###############################################################################
# Dev sample pages — design/effect previews (dev mode only)
###############################################################################

@app.route("/dev/glitch-sample")
def glitch_sample():
    """Preview page for tagline glitch animation effects"""
    if AUTH_MODE != "dev":
        return redirect(url_for("index"))
    return render_template("glitch_sample.html")
