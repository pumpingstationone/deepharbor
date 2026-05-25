"""
Webhook notification dispatcher for DHEquipment.

Reads the notification config stored in equipment_config (key="notifications")
and fires HTTP POST requests to configured webhook endpoints when equipment
events occur.

Event names:
  ticket_opened, ticket_closed, ticket_status_changed,
  equipment_status_changed,
  maintenance_due, maintenance_started, maintenance_completed, maintenance_overdue
"""

import asyncio
import hashlib
import hmac
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

import db
from dhs_logging import logger


# Human-readable labels for Discord embeds
_EVENT_LABELS = {
    "ticket_opened":            "Ticket Opened",
    "ticket_closed":            "Ticket Closed",
    "ticket_status_changed":    "Ticket Status Changed",
    "equipment_status_changed": "Equipment Status Changed",
    "maintenance_due":          "Maintenance Due",
    "maintenance_started":      "Maintenance Started",
    "maintenance_completed":    "Maintenance Completed",
    "maintenance_overdue":      "Maintenance Overdue",
}

_DISCORD_COLORS = {
    "ticket_opened":            0x5865F2,   # Discord blurple
    "ticket_closed":            0x57F287,   # Green
    "ticket_status_changed":    0xFEE75C,   # Yellow
    "equipment_status_changed": 0xEB459E,   # Pink
    "maintenance_due":          0xED4245,   # Red
    "maintenance_started":      0x5865F2,
    "maintenance_completed":    0x57F287,
    "maintenance_overdue":      0xED4245,
}


def _event_matches_webhook(event_name: str, wh_events: list) -> bool:
    """Return True if this webhook should fire for this event."""
    if not wh_events:
        return True
    if "*" in wh_events:
        return True
    return event_name in wh_events


def _build_discord_body(event_name: str, payload: dict, username: str, avatar_url: str,
                        style: dict = None) -> dict:
    style = style or {}
    label = _EVENT_LABELS.get(event_name, event_name)
    ts = datetime.now(timezone.utc).isoformat()

    # Title: optional prefix prepended to the event label
    title_prefix = style.get("title_prefix", "").strip()
    embed_title = f"{title_prefix} {label}".strip() if title_prefix else label

    # Color: custom hex overrides per-event default; empty = use per-event default
    custom_color = style.get("color", "").strip().lstrip("#")
    if custom_color:
        try:
            color = int(custom_color, 16)
        except ValueError:
            color = _DISCORD_COLORS.get(event_name, 0x5865F2)
    else:
        color = _DISCORD_COLORS.get(event_name, 0x5865F2)

    # Description: use template if provided, otherwise auto-generate from payload fields
    desc_template = style.get("description_template", "").strip()
    if desc_template:
        try:
            description = desc_template.format_map({**payload, "event": event_name})
        except (KeyError, ValueError):
            description = desc_template
    else:
        lines = []
        for key in ("title", "name", "common_name", "status", "priority", "equipment_id", "ticket_id", "id"):
            val = payload.get(key)
            if val is not None:
                lines.append(f"**{key.replace('_', ' ').title()}:** {val}")
        description = "\n".join(lines) if lines else "No additional details."

    # Footer text: custom or default
    footer_text = style.get("footer", "").strip() or "Deep Harbor Equipment"

    body: dict = {
        "embeds": [
            {
                "title": embed_title,
                "description": description,
                "color": color,
                "footer": {"text": footer_text},
                "timestamp": ts,
            }
        ]
    }

    # Content: plain text above the embed (supports emoji/markdown)
    content = style.get("content", "").strip()
    if content:
        body["content"] = content

    if username:
        body["username"] = username
    if avatar_url:
        body["avatar_url"] = avatar_url
    return body


def _build_generic_body(event_name: str, payload: dict) -> dict:
    return {
        "event": event_name,
        "source": "dh-equipment",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }


def _sign_body(body_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body_bytes, hashlib.sha256)  # type: ignore[attr-defined]
    return "sha256=" + mac.hexdigest()


def _dispatch_webhook_sync(wh: dict, event_name: str, payload: dict):
    """Fire a single webhook synchronously. Errors are logged but never raised."""
    url = wh.get("url", "").strip()
    if not url:
        return

    wh_type = wh.get("type", "generic")
    secret = wh.get("secret", "")
    name = wh.get("name") or url

    try:
        if wh_type == "discord":
            username = wh.get("discord_username", "DH Equipment")
            avatar_url = wh.get("discord_avatar_url", "")
            style = wh.get("discord_style", {})
            send_body = _build_discord_body(event_name, payload, username, avatar_url, style)
        else:
            send_body = _build_generic_body(event_name, payload)

        body_bytes = json.dumps(send_body).encode()
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, 10)",
            },
            method="POST",
        )
        if secret and wh_type != "discord":
            req.add_header("X-DH-Signature", _sign_body(body_bytes, secret))

        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Webhook '{name}' event={event_name} → {resp.status}")
    except urllib.error.HTTPError as exc:
        logger.warning(f"Webhook '{name}' event={event_name} HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        logger.warning(f"Webhook '{name}' event={event_name} failed: {exc}")


async def fire_event(event_name: str, payload: dict):
    """
    Dispatch event to all matching, enabled webhooks.

    Respects the per-event 'webhook' toggle in the events matrix, then
    fires each enabled webhook whose event filter matches.

    This is safe to call with asyncio.create_task() for fire-and-forget.
    """
    try:
        cfg = db.load_notification_config()
        if not cfg:
            return

        # Check if the 'webhook' channel is enabled for this event
        events_matrix = cfg.get("events", {})
        evt_cfg = events_matrix.get(event_name, {})
        if not evt_cfg.get("webhook", False):
            return

        webhooks = cfg.get("webhooks", [])
        if not webhooks:
            return

        loop = asyncio.get_event_loop()
        for wh in webhooks:
            if not wh.get("enabled", True):
                continue
            if _event_matches_webhook(event_name, wh.get("events", ["*"])):
                # Run sync HTTP call in thread pool so it doesn't block the event loop
                await loop.run_in_executor(None, _dispatch_webhook_sync, wh, event_name, payload)
    except Exception as exc:
        logger.warning(f"fire_event({event_name}) error: {exc}")


def schedule_event(event_name: str, payload: dict):
    """
    Schedule fire_event as a background asyncio task.
    Call this from sync or async contexts where you don't want to await.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(fire_event(event_name, payload))
        else:
            loop.run_until_complete(fire_event(event_name, payload))
    except Exception as exc:
        logger.warning(f"schedule_event({event_name}) could not schedule: {exc}")
