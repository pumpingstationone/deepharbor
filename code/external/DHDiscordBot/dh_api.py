"""
Deep Harbor Equipment API Client
Handles OAuth2 client-credential authentication and all API calls for the Discord bot.
Adapted from PA1's pa1_api.py — changed from user-login auth to DH client credentials,
updated API paths, and changed ID types from UUID to integer.
"""
import httpx
import time
import logging

log = logging.getLogger("dh_api")


class DHEquipmentClient:
    def __init__(self, base_url: str, client_name: str, client_secret: str,
                 bot_member_id: int = None, bot_permissions: dict = None):
        self.base_url = base_url.rstrip("/")
        self.client_name = client_name
        self.client_secret = client_secret
        self.bot_member_id = bot_member_id
        self.bot_permissions = bot_permissions or {"view": ["all"], "change": ["all"]}
        self.token: str | None = None
        self.token_expiry: float = 0
        self._client = httpx.AsyncClient(timeout=15)

    async def close(self):
        await self._client.aclose()

    async def _ensure_token(self):
        """Authenticate with DH OAuth2 client credentials."""
        if self.token and time.time() < self.token_expiry - 60:
            return
        log.info(f"Authenticating as client '{self.client_name}'...")
        resp = await self._client.post(
            f"{self.base_url}/token",
            data={"username": self.client_name, "password": self.client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        self.token = data["access_token"]
        # DH tokens expire in 30 min by default; refresh at 25 min
        self.token_expiry = time.time() + 25 * 60
        log.info(f"Authenticated as client '{self.client_name}'")

    async def _headers(self) -> dict:
        """Build request headers with auth token and member context."""
        await self._ensure_token()
        import json
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if self.bot_member_id:
            headers["X-Member-ID"] = str(self.bot_member_id)
        if self.bot_permissions:
            headers["X-Member-Permissions"] = json.dumps(self.bot_permissions)
        headers["X-Member-Role"] = "Bot"
        return headers

    async def get(self, path: str, params: dict | None = None) -> dict | list:
        headers = await self._headers()
        resp = await self._client.get(f"{self.base_url}{path}", headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, json_data: dict | None = None) -> dict:
        headers = await self._headers()
        resp = await self._client.post(f"{self.base_url}{path}", headers=headers, json=json_data)
        resp.raise_for_status()
        return resp.json()

    async def patch(self, path: str, json_data: dict | None = None) -> dict:
        headers = await self._headers()
        resp = await self._client.patch(f"{self.base_url}{path}", headers=headers, json=json_data)
        resp.raise_for_status()
        return resp.json()

    # ── Convenience methods ──────────────────────────────────────

    async def search_equipment(self, query: str = "", limit: int = 25) -> list:
        """Search equipment by name/make/model."""
        params = {}
        if query:
            params["search"] = query
        items = await self.get("/v1/equipment/items", params=params)
        return items[:limit] if isinstance(items, list) else []

    async def get_equipment(self, equipment_id: int) -> dict:
        return await self.get(f"/v1/equipment/items/{equipment_id}")

    async def create_ticket(self, equipment_id: int, title: str,
                            description: str = "", priority: str = "normal",
                            metadata: dict | None = None) -> dict:
        payload = {
            "equipment_id": equipment_id,
            "title": title,
            "description": description,
            "priority": priority,
            "metadata": metadata or {},
        }
        return await self.post("/v1/equipment/tickets", payload)

    async def add_worklog(self, ticket_id: int, action: str,
                          notes: str = "") -> dict:
        payload = {
            "action": action,
            "notes": notes,
            "parts_used": [],
            "attachments": [],
        }
        return await self.post(f"/v1/equipment/tickets/{ticket_id}/worklog", payload)

    async def get_ticket(self, ticket_id: int) -> dict:
        return await self.get(f"/v1/equipment/tickets/{ticket_id}")

    async def list_tickets(self, status: str | None = None,
                           equipment_id: int | None = None,
                           limit: int = 10) -> list:
        params = {}
        if status:
            params["status"] = status
        if equipment_id:
            params["equipment_id"] = str(equipment_id)
        items = await self.get("/v1/equipment/tickets", params=params)
        return items[:limit] if isinstance(items, list) else []

    async def get_ticket_by_number(self, ticket_number: str) -> dict | None:
        """Find a ticket by its TKT-XXXXXX number."""
        tickets = await self.get("/v1/equipment/tickets")
        if isinstance(tickets, list):
            for t in tickets:
                if t.get("ticket_number", "").upper() == ticket_number.upper():
                    return t
        return None
