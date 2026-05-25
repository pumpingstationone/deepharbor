"""
Deep Harbor Equipment Management Portal
Flask application with Azure B2C SSO, proxying to DHEquipment API.
"""

import json
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, session, request, redirect, url_for, jsonify, flash
from flask_session import Session
from flask_wtf.csrf import CSRFProtect, CSRFError
import msal

import dhservices
from dhs_logging import logger
import app_config
from config import config

###############################################################################
# App Setup
###############################################################################

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
    if (request.is_json or request.content_type == "application/json"
            or request.headers.get("X-CSRFToken") is not None):
        return {"error": "CSRF token missing or invalid"}, 400
    flash("Your session has expired. Please try again.", "error")
    return redirect(request.referrer or url_for("index"))


###############################################################################
# Health Check
###############################################################################

@app.route("/health")
def health():
    return "OK", 200


###############################################################################
# Member Context Helper
###############################################################################

def _member_context():
    """Get member_id, permissions, and role from the current session."""
    return {
        "member_id": session.get("member_id"),
        "permissions": session.get("user_permissions", {}),
        "role": session.get("user_role", ""),
    }


def _require_equipment_perm(perm_type: str, perm_key: str):
    """Check if current user has a specific equipment permission."""
    perms = session.get("user_permissions", {})
    perm_list = perms.get(perm_type, [])
    if "all" in perm_list or perm_key in perm_list:
        return True
    # change implies view
    if perm_type == "view":
        change_list = perms.get("change", [])
        if "all" in change_list or perm_key in change_list:
            return True
    return False


###############################################################################
# B2C Auth Routes
###############################################################################

@app.route("/")
def index():
    if not session.get("user"):
        if AUTH_MODE == "dev":
            return redirect(url_for("dev_login"))
        session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
        return render_template(
            "index.html", auth_url=session["flow"]["auth_uri"], version=msal.__version__
        )
    else:
        # Refresh roles/permissions on each page load
        _refresh_member_context()

        return render_template(
            "index.html",
            user=session["user"],
            member_id=session.get("member_id"),
            user_role=session.get("user_role", "Unknown"),
            user_permissions=session.get("user_permissions", {}),
            admin_base_url=config.get("dh_admin", "base_url", fallback="http://localhost:5001"),
        )


def _refresh_member_context():
    """Fetch fresh member ID, roles, and permissions from DHService."""
    try:
        access_token = dhservices.get_access_token(
            dhservices.DH_CLIENT_ID, dhservices.DH_CLIENT_SECRET
        )
        user_email = session["user"].get("email") or session["user"].get("preferred_username")
        member_data = dhservices.get_member_id(access_token, user_email)
        member_id = member_data.get("member_id")
        session["member_id"] = member_id

        if member_id:
            roles_data = dhservices.get_member_roles(access_token, str(member_id))
            if roles_data and "roles" in roles_data and len(roles_data["roles"]) > 0:
                role_info = roles_data["roles"][0]
                session["user_role"] = role_info.get("role_name", "Unknown")
                session["user_permissions"] = role_info.get("permission", {})
            else:
                session["user_role"] = "No Role"
                session["user_permissions"] = {}
        else:
            session["user_role"] = "Unknown"
            session["user_permissions"] = {}
    except Exception as e:
        logger.error(f"Error fetching member context: {e}")
        session["user_role"] = session.get("user_role", "Error")
        session["user_permissions"] = session.get("user_permissions", {})


@app.route("/login")
def login():
    if AUTH_MODE == "dev":
        return redirect(url_for("dev_login"))
    session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
    return redirect(session["flow"]["auth_uri"])


@app.route(app_config.REDIRECT_PATH)
def authorized():
    try:
        cache = _load_cache()
        result = _build_msal_app(cache=cache).acquire_token_by_auth_code_flow(
            session.get("flow", {}), request.args
        )
        if "error" in result:
            return render_template("auth_error.html", result=result)

        user_claims = result.get("id_token_claims")

        # Verify user has roles
        try:
            access_token = dhservices.get_access_token(
                dhservices.DH_CLIENT_ID, dhservices.DH_CLIENT_SECRET
            )
            user_email = user_claims.get("email") or user_claims.get("preferred_username")
            if not user_email:
                return render_template("auth_error.html", result={
                    "error": "Authorization Failed",
                    "error_description": "No email address found in your account."
                })

            member_data = dhservices.get_member_id(access_token, user_email)
            member_id = member_data.get("member_id")
            if not member_id:
                return render_template("auth_error.html", result={
                    "error": "Authorization Failed",
                    "error_description": "Your account is not registered in the system."
                })

            roles_data = dhservices.get_member_roles(access_token, str(member_id))
            if not roles_data or "roles" not in roles_data or len(roles_data["roles"]) == 0:
                return render_template("auth_error.html", result={
                    "error": "Authorization Failed",
                    "error_description": "No roles have been assigned to your account."
                })

            # User authorized
            session["user"] = user_claims
            session["member_id"] = member_id
            _save_cache(cache)

            # Log login
            try:
                dhservices.log_user_activity(access_token, str(member_id), {
                    "activity_details": {
                        "action": "equipment_portal_login",
                        "email": user_email,
                    }
                })
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error during authorization: {e}")
            return render_template("auth_error.html", result={
                "error": "Authorization Error",
                "error_description": str(e),
            })

    except ValueError:
        pass
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    if AUTH_MODE == "dev":
        return redirect(url_for("index"))
    return redirect(
        app_config.AUTHORITY + "/oauth2/v2.0/logout"
        + "?post_logout_redirect_uri=" + url_for("index", _external=True)
    )


###############################################################################
# Dev Login (dev mode only)
###############################################################################

@app.route("/dev_login", methods=["GET", "POST"])
def dev_login():
    if AUTH_MODE != "dev":
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "dev@example.com")
        session["user"] = {
            "name": "Dev User",
            "email": email,
            "preferred_username": email,
        }
        # Fetch member info
        try:
            access_token = dhservices.get_access_token(
                dhservices.DH_CLIENT_ID, dhservices.DH_CLIENT_SECRET
            )
            member_data = dhservices.get_member_id(access_token, email)
            session["member_id"] = member_data.get("member_id")
            if session["member_id"]:
                roles_data = dhservices.get_member_roles(access_token, str(session["member_id"]))
                if roles_data and "roles" in roles_data and len(roles_data["roles"]) > 0:
                    role_info = roles_data["roles"][0]
                    session["user_role"] = role_info.get("role_name", "Unknown")
                    session["user_permissions"] = role_info.get("permission", {})
        except Exception as e:
            logger.error(f"Dev login error: {e}")
            # Default to full permissions in dev mode
            session["user_role"] = "Administrator"
            session["user_permissions"] = {
                "view": ["all"],
                "change": ["all"],
            }

        return redirect(url_for("index"))

    return render_template("dev_login.html")


###############################################################################
# Equipment API Proxy Routes
# The frontend SPA makes fetch() calls to these /api/* routes,
# and we proxy them to the DHEquipment service with member context headers.
###############################################################################

def _proxy_get(equip_path: str, **extra_params):
    """Proxy a GET request to the equipment API."""
    ctx = _member_context()
    params = dict(request.args)
    params.update(extra_params)
    try:
        result = dhservices._equip_get(equip_path, **ctx, params=params)
        return jsonify(result)
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


def _proxy_post(equip_path: str, data: dict = None):
    ctx = _member_context()
    body = data if data is not None else request.get_json(silent=True) or {}
    try:
        result = dhservices._equip_post(equip_path, body, **ctx)
        return jsonify(result), 201
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


def _proxy_patch(equip_path: str):
    ctx = _member_context()
    body = request.get_json(silent=True) or {}
    try:
        result = dhservices._equip_patch(equip_path, body, **ctx)
        return jsonify(result)
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


def _proxy_put(equip_path: str):
    ctx = _member_context()
    body = request.get_json(silent=True) or {}
    try:
        result = dhservices._equip_put(equip_path, body, **ctx)
        return jsonify(result)
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


def _proxy_delete(equip_path: str):
    ctx = _member_context()
    try:
        dhservices._equip_delete(equip_path, **ctx)
        return "", 204
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500


# ── Areas ──
@app.route("/api/areas", methods=["GET"])
def api_list_areas():
    return _proxy_get("/v1/equipment/areas")

@app.route("/api/areas", methods=["POST"])
def api_create_area():
    return _proxy_post("/v1/equipment/areas")

@app.route("/api/areas/<int:area_id>", methods=["GET"])
def api_get_area(area_id):
    return _proxy_get(f"/v1/equipment/areas/{area_id}")

@app.route("/api/areas/<int:area_id>", methods=["PATCH"])
def api_update_area(area_id):
    return _proxy_patch(f"/v1/equipment/areas/{area_id}")

@app.route("/api/areas/<int:area_id>", methods=["DELETE"])
def api_delete_area(area_id):
    return _proxy_delete(f"/v1/equipment/areas/{area_id}")


# ── Equipment ──
@app.route("/api/equipment", methods=["GET"])
def api_list_equipment():
    return _proxy_get("/v1/equipment/items")

@app.route("/api/equipment/<int:equipment_id>", methods=["GET"])
def api_get_equipment(equipment_id):
    return _proxy_get(f"/v1/equipment/items/{equipment_id}")

@app.route("/api/equipment", methods=["POST"])
def api_create_equipment():
    return _proxy_post("/v1/equipment/items")

@app.route("/api/equipment/<int:equipment_id>", methods=["PATCH"])
def api_update_equipment(equipment_id):
    return _proxy_patch(f"/v1/equipment/items/{equipment_id}")

@app.route("/api/equipment/<int:equipment_id>", methods=["DELETE"])
def api_delete_equipment(equipment_id):
    return _proxy_delete(f"/v1/equipment/items/{equipment_id}")


# ── Tickets ──
@app.route("/api/tickets", methods=["GET"])
def api_list_tickets():
    return _proxy_get("/v1/equipment/tickets")

@app.route("/api/tickets/<int:ticket_id>", methods=["GET"])
def api_get_ticket(ticket_id):
    return _proxy_get(f"/v1/equipment/tickets/{ticket_id}")

@app.route("/api/tickets", methods=["POST"])
def api_create_ticket():
    return _proxy_post("/v1/equipment/tickets")

@app.route("/api/tickets/<int:ticket_id>", methods=["PATCH"])
def api_update_ticket(ticket_id):
    return _proxy_patch(f"/v1/equipment/tickets/{ticket_id}")

@app.route("/api/tickets/<int:ticket_id>", methods=["DELETE"])
def api_delete_ticket(ticket_id):
    return _proxy_delete(f"/v1/equipment/tickets/{ticket_id}")

@app.route("/api/tickets/<int:ticket_id>/worklog", methods=["POST"])
def api_add_worklog(ticket_id):
    return _proxy_post(f"/v1/equipment/tickets/{ticket_id}/worklog")


# ── Schedules ──
@app.route("/api/schedules", methods=["GET"])
def api_list_schedules():
    return _proxy_get("/v1/equipment/schedules")

@app.route("/api/schedules", methods=["POST"])
def api_create_schedule():
    return _proxy_post("/v1/equipment/schedules")

@app.route("/api/schedules/<int:schedule_id>", methods=["DELETE"])
def api_delete_schedule(schedule_id):
    return _proxy_delete(f"/v1/equipment/schedules/{schedule_id}")


# ── Auth Sessions ──
@app.route("/api/auth-sessions", methods=["GET"])
def api_list_auth_sessions():
    return _proxy_get("/v1/equipment/auth-sessions")

@app.route("/api/auth-sessions/<int:session_id>", methods=["GET"])
def api_get_auth_session(session_id):
    return _proxy_get(f"/v1/equipment/auth-sessions/{session_id}")

@app.route("/api/auth-sessions", methods=["POST"])
def api_create_auth_session():
    return _proxy_post("/v1/equipment/auth-sessions")

@app.route("/api/auth-sessions/<int:session_id>", methods=["PATCH"])
def api_update_auth_session(session_id):
    return _proxy_patch(f"/v1/equipment/auth-sessions/{session_id}")

@app.route("/api/auth-sessions/<int:session_id>", methods=["DELETE"])
def api_delete_auth_session(session_id):
    return _proxy_delete(f"/v1/equipment/auth-sessions/{session_id}")

@app.route("/api/auth-sessions/<int:session_id>/enroll", methods=["POST"])
def api_enroll(session_id):
    return _proxy_post(f"/v1/equipment/auth-sessions/{session_id}/enroll", data={})

@app.route("/api/auth-sessions/<int:session_id>/enroll", methods=["DELETE"])
def api_unenroll(session_id):
    return _proxy_delete(f"/v1/equipment/auth-sessions/{session_id}/enroll")


# ── Groups ──
@app.route("/api/equipment-groups", methods=["GET"])
def api_list_groups():
    return _proxy_get("/v1/equipment/groups")

@app.route("/api/equipment-groups", methods=["POST"])
def api_create_group():
    return _proxy_post("/v1/equipment/groups")

@app.route("/api/equipment-groups/<int:group_id>", methods=["PATCH"])
def api_update_group(group_id):
    return _proxy_patch(f"/v1/equipment/groups/{group_id}")

@app.route("/api/equipment-groups/<int:group_id>", methods=["DELETE"])
def api_delete_group(group_id):
    return _proxy_delete(f"/v1/equipment/groups/{group_id}")


# ── Maintenance ──
@app.route("/api/maintenance/schedules", methods=["GET"])
def api_list_maint_schedules():
    return _proxy_get("/v1/equipment/maintenance/schedules")

@app.route("/api/maintenance/schedules", methods=["POST"])
def api_create_maint_schedule():
    return _proxy_post("/v1/equipment/maintenance/schedules")

@app.route("/api/maintenance/schedules/<int:schedule_id>", methods=["PATCH"])
def api_update_maint_schedule(schedule_id):
    return _proxy_patch(f"/v1/equipment/maintenance/schedules/{schedule_id}")

@app.route("/api/maintenance/schedules/<int:schedule_id>", methods=["DELETE"])
def api_delete_maint_schedule(schedule_id):
    return _proxy_delete(f"/v1/equipment/maintenance/schedules/{schedule_id}")

@app.route("/api/maintenance/events", methods=["GET"])
def api_list_maint_events():
    return _proxy_get("/v1/equipment/maintenance/events")

@app.route("/api/maintenance/events/<int:event_id>", methods=["PATCH"])
def api_update_maint_event(event_id):
    return _proxy_patch(f"/v1/equipment/maintenance/events/{event_id}")


# ── File Upload ──
@app.route("/api/upload", methods=["POST"])
def api_upload():
    ctx = _member_context()
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400
    entity_type = request.form.get("entity_type", "equipment_location")
    entity_id = request.form.get("entity_id", "new")
    try:
        token = dhservices.get_access_token(dhservices.EQUIP_CLIENT_ID, dhservices.EQUIP_CLIENT_SECRET, dhservices.EQUIP_API_BASE_URL)
        headers = dhservices._member_headers(token, **ctx)
        resp = requests.post(
            f"{dhservices.EQUIP_API_BASE_URL}/v1/equipment/upload",
            headers=headers,
            files={"file": (f.filename, f.stream, f.content_type)},
            data={"entity_type": entity_type, "entity_id": entity_id},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        # Rewrite the storage URL to a portal-relative path so it works
        # regardless of how the portal is accessed (tunneled, proxied, etc.)
        if data.get("key"):
            data["url"] = f"/api/media/{data['key']}"
        return jsonify(data), 200
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500
    except Exception as e:
        logger.error(f"Upload proxy error: {e}")
        return jsonify({"error": "Upload failed"}), 500


# ── Media proxy ──
@app.route("/api/media/<path:key>")
def api_media(key):
    try:
        token = dhservices.get_access_token(dhservices.EQUIP_CLIENT_ID, dhservices.EQUIP_CLIENT_SECRET, dhservices.EQUIP_API_BASE_URL)
        headers = dhservices._member_headers(token, **_member_context())
        resp = requests.get(
            f"{dhservices.EQUIP_API_BASE_URL}/v1/equipment/media/{key}",
            headers=headers,
            timeout=60,
            stream=True,
        )
        resp.raise_for_status()
        from flask import Response
        return Response(resp.raw.read(), content_type=resp.headers.get("Content-Type", "application/octet-stream"))
    except Exception as e:
        logger.error(f"Media proxy error: {e}")
        return "", 404


@app.route("/api/media/<path:key>", methods=["DELETE"])
def api_delete_media(key):
    try:
        token = dhservices.get_access_token(dhservices.EQUIP_CLIENT_ID, dhservices.EQUIP_CLIENT_SECRET, dhservices.EQUIP_API_BASE_URL)
        headers = dhservices._member_headers(token, **_member_context())
        resp = requests.delete(
            f"{dhservices.EQUIP_API_BASE_URL}/v1/equipment/media/{key}",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return "", 204
    except requests.HTTPError as e:
        return jsonify({"error": str(e)}), e.response.status_code if e.response else 500
    except Exception as e:
        logger.error(f"Media delete proxy error: {e}")
        return jsonify({"error": "Delete failed"}), 500


# ── Dashboard / Config / Export ──
@app.route("/api/stats", methods=["GET"])
def api_stats():
    return _proxy_get("/v1/equipment/dashboard/stats")

@app.route("/api/config/<key>", methods=["GET"])
def api_get_config(key):
    return _proxy_get(f"/v1/equipment/config/{key}")

@app.route("/api/config/<key>", methods=["PUT"])
def api_set_config(key):
    return _proxy_put(f"/v1/equipment/config/{key}")



@app.route("/api/webhook-test", methods=["POST"])
def api_webhook_test():
    """Send a test payload to a webhook URL server-side (avoids CORS)."""
    body = request.get_json(silent=True) or {}
    url = body.get("url", "").strip()
    wh_type = body.get("type", "generic")
    secret = body.get("secret", "")
    discord_username = body.get("discord_username", "DH Equipment")
    discord_avatar = body.get("discord_avatar_url", "")
    discord_style = body.get("discord_style", {})

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    ts = datetime.utcnow().isoformat() + "Z"
    test_payload = {"title": "Test Event", "status": "test", "event": "test"}

    try:
        if wh_type == "discord":
            import hmac as _hmac, hashlib as _hashlib

            # Apply discord_style the same way notifications.py does
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

            discord_headers = {
                "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)",
            }
            resp = requests.post(url, json=send_body, headers=discord_headers, timeout=10)
        else:
            generic_payload = {
                "event": "test",
                "source": "dh-equipment",
                "message": "This is a test notification from Deep Harbor Equipment Management.",
                "timestamp": ts,
            }
            headers = {"Content-Type": "application/json"}
            if secret:
                import hmac, hashlib
                sig = hmac.new(secret.encode(), json.dumps(generic_payload).encode(), hashlib.sha256).hexdigest()
                headers["X-DH-Signature"] = f"sha256={sig}"
            resp = requests.post(url, json=generic_payload, headers=headers, timeout=10)

        return jsonify({"status": resp.status_code, "ok": resp.ok}), 200
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Could not connect to webhook URL"}), 502
    except requests.exceptions.Timeout:
        return jsonify({"error": "Webhook URL timed out"}), 504
    except Exception as e:
        logger.error(f"Webhook test error: {e}")
        return jsonify({"error": str(e)}), 500


###############################################################################
# MSAL / B2C Helpers
###############################################################################

def _load_cache():
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])
    return cache

def _save_cache(cache):
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()

def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        app_config.CLIENT_ID,
        authority=authority or app_config.AUTHORITY,
        client_credential=app_config.CLIENT_SECRET,
        token_cache=cache,
    )

def _build_auth_code_flow(authority=None, scopes=None):
    return _build_msal_app(authority=authority).initiate_auth_code_flow(
        scopes or [], redirect_uri=url_for("authorized", _external=True)
    )

###############################################################################
# Template Context
###############################################################################

app.jinja_env.globals.update(_build_auth_code_flow=_build_auth_code_flow)
app.jinja_env.globals.update(git_version=config.get("git", "version", fallback="unknown"))
app.jinja_env.globals.update(now=datetime.now)
app.jinja_env.globals.update(auth_mode=AUTH_MODE)
app.jinja_env.globals.update(dev_banner=DEV_BANNER)

@app.context_processor
def inject_theme():
    """Inject equipment theme — defaults to 'clean'."""
    theme = session.get("equip_theme", "clean")
    valid = ("bubblegum", "light", "dark", "midnight", "hacker", "clean")
    if theme not in valid:
        theme = "clean"
    return {"equip_theme": theme}

@app.context_processor
def inject_csrf():
    from flask_wtf.csrf import generate_csrf
    return {"csrf_token": generate_csrf}
