# DHEquipment

Deep Harbor Equipment Management Service — provides the backend API for equipment inventory, repair tickets, scheduling, authorization sessions, maintenance tracking, and equipment groups.

## Setup

1. Copy `config.ini.example` to `config.ini` and update with your database and OAuth2 credentials.
2. Generate a `uv.lock` file: `uv sync`
3. Run locally: `uv run uvicorn main:app --host 0.0.0.0 --port 8000`

Or via Docker (from the project root):
```
docker-compose up --build dhequipment
```

## API

All endpoints are under `/v1/equipment/`. See `/routes` for a full list.

Authentication uses OAuth2 client credentials — POST to `/token` with the `dev-equipment-portal` client name and secret.

Member identity and permissions are passed via `X-Member-ID`, `X-Member-Permissions`, and `X-Member-Role` request headers set by the portal's Flask backend after SSO authentication.

## Note on uv.lock

The `uv.lock` file must be generated before the Docker build will succeed. Run `uv sync` in this directory to create it.
