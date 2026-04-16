# Deep Harbor — Dev Environment Setup

Set up and run Deep Harbor locally for development. The dev environment
runs entirely in Docker with no external dependencies (no Azure B2C,
no Active Directory, no RFID hardware, no Stripe, no Mailgun).

## Prerequisites

- **Docker** and **Docker Compose** (v2.24.0+, with `docker compose` syntax)
- **uv** — Python package runner, needed for seed data generation
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Git**

## Quick Start

```bash
git clone https://github.com/pumpingstationone/deepharbor.git
cd deepharbor
git checkout dev
./dh_dev.sh setup
```

`dh_dev.sh setup` copies config files, generates seed data, and starts
all containers. First build takes a few minutes.

## Day-to-Day Commands

```bash
./dh_dev.sh start    # Build and start the dev environment
./dh_dev.sh stop     # Stop containers (database persists)
./dh_dev.sh reset    # Full reset: remove volumes, rebuild, start (re-seeds DB)
./dh_dev.sh clean    # Remove all dev artifacts (return to fresh clone state)
./dh_dev.sh status   # Show container status
```

## Access Points

| Service         | URL                        | Credentials     |
|-----------------|----------------------------|-----------------|
| Admin Portal    | http://localhost:5001      | Dev user picker  |
| Member Portal   | http://localhost:5002      | Dev user picker  |
| API Gateway     | http://localhost:8808      | OAuth2 token     |
| PostgreSQL      | localhost:5432             | dh / dh          |
| Grafana         | http://localhost:3300      | admin / admin    |

## What the Dev Environment Does Differently

The dev compose overlay (`docker-compose.dev.yml`) makes these changes
on top of the production compose file:

1. **Disables hardware services** — AD controller, RFID reader, and
   RFID2DB are gated behind a `hardware` profile and won't start
2. **Switches to bridge networking** — Portals and ST2DH move from
   `network_mode: host` to the Docker bridge network
3. **Bypasses authentication** — `AUTH_MODE=dev` replaces Azure B2C
   login with a dev user picker showing preset seed-data members
4. **Shows dev banner** — `DEV_BANNER=true` displays a "DEV MODE"
   banner at the top of every portal page
5. **Bypasses external calls** — `DEV_MODE=true` on worker services
   (DH2AD, DH2RFID) so they return success without contacting
   hardware controllers
6. **Loads seed data** — 25 members inserted on first boot (10 dev
   users with stable IDs + 15 random members)
7. **Sets Flask secret key** — `DH_SECRET_KEY` is set automatically
   for CSRF protection and session security (production requires
   generating your own — see [README.md](README.md))
8. **Remaps ports** — Gateway 80→8808, Grafana 3000→3300 to avoid
   conflicts with other local services

## Dev Auth Bypass

When `AUTH_MODE=dev`, the portals show a user picker instead of the
Azure B2C login flow. You can select a preset user or enter any member
ID manually.

**Admin Portal** (http://localhost:5001):

| Name            | ID | Role          |
|-----------------|----|---------------|
| Ada Lovelace    | 1  | Administrator |
| Nikola Tesla    | 3  | Authorizer    |
| Grace Hopper    | 5  | Board         |

**Member Portal** (http://localhost:5002):

| Name               | ID | Description                   |
|--------------------|----|-------------------------------|
| Rosalind Franklin  | 7  | Active member with full data  |
| Dorothy Vaughan    | 16 | Brand new member, minimal data |
| Marie Curie        | 9  | Inactive member               |

Authorization still works normally — the portals make real API calls
to DHService to check roles and permissions. Only the Azure B2C
authentication step is bypassed.

## Dev Banner

The `DEV_BANNER` env var controls the "DEV MODE" banner shown at the
top of every portal page. It's independent of `AUTH_MODE` — you can
use them separately or together:

| AUTH_MODE | DEV_BANNER | Result |
|-----------|------------|--------|
| *(unset)* | *(unset)*  | Normal B2C login, no banner (production) |
| `dev`     | `true`     | Dev login picker + banner (full dev, the default in docker-compose.dev.yml) |
| *(unset)* | `true`     | Real B2C login + banner (staging/test deployments) |
| `dev`     | *(unset)*  | Dev login picker, no banner |

To show the banner on a non-dev deployment, set the `DEV_BANNER`
environment variable on the portal containers:

```yaml
environment:
  DEV_BANNER: "true"
```

## Manual Setup

If you prefer not to use `dh_dev.sh setup`:

### 1. Copy Config Files

Every service needs a `config.ini`. The `.example` files work as-is
for dev:

```bash
find code -name "config.ini.example" -exec sh -c \
  'for f; do cp -n "$f" "${f%.example}"; done' _ {} +
```

Config files are gitignored and will never be committed.

The Grafana service also needs an env file for Okta configuration.
Copy the example file (the defaults work for dev):

```bash
cp -n .env.grafana.okta.example .env.grafana.okta.production
```

### 2. Generate Seed Data

```bash
tools/seed_data.sh generate              # 25 members (15 random + 10 dev)
tools/seed_data.sh generate 100          # 110 members (100 random + 10 dev)
tools/seed_data.sh generate 50 myseed    # Reproducible with a specific seed
tools/seed_data.sh static                # Hand-crafted static data (25 members)
tools/seed_data.sh status                # Show current seed data info
```

Output goes to `pg/sql/seed_data.local.sql` (gitignored), which is
mounted into the database container during init. The static reference
data lives in `pg/sql/seed_data.sql` (committed to git).

### 3. Start / Stop

```bash
# Start
docker compose -f docker-compose.yaml -f docker-compose.dev.yml up --build -d

# Stop (preserves database)
docker compose -f docker-compose.yaml -f docker-compose.dev.yml down

# Stop and reset database
docker compose -f docker-compose.yaml -f docker-compose.dev.yml down --volumes
```

## Config Files

All 14 services have a `config.ini.example` that works for dev:

| Category | Services | Dev Notes |
|----------|----------|-----------|
| Core API | DHService, DHDispatcher | Fully functional, talks to local DB |
| Portals | DHAdminPortal, DHMemberPortal | B2C fields blank; AUTH_MODE=dev bypasses login |
| Business | DHAccess, DHAuthorizations, DHIdentity, DHStatus | Fully functional |
| Workers | DH2AD, DH2RFID | DEV_MODE=true bypasses hardware calls |
| External | ST2DH, WF2DH, DH2MG | Creds blank; won't receive/send external data |
| Utilities | RFID2DB | Disabled in dev (hardware profile) |
| Grafana | .env.grafana.okta.production | Copied from .env.grafana.okta.example; Okta fields blank in dev |

## Seed Data

The first 10 members (IDs 1–10) are stable "dev bypass" users with
known names and roles. They are always included regardless of whether
you use `generate` or `static` mode.

| ID | Name               | Role          |
|----|--------------------|---------------|
| 1  | Ada Lovelace       | Administrator |
| 2  | Charles Babbage    | Administrator |
| 3  | Nikola Tesla       | Authorizer    |
| 4  | Marie Curie        | Authorizer    |
| 5  | Grace Hopper       | Board         |
| 6  | Alan Turing        | Board         |
| 7  | Rosalind Franklin  | Active Member |
| 8  | Linus Torvalds     | Active Member |
| 9  | Margaret Hamilton  | Inactive      |
| 10 | Dennis Ritchie     | Inactive      |

The seed data only loads on first boot (PostgreSQL initdb). If the
volume already has data, init scripts are skipped. Use `./dh_dev.sh reset`
to re-seed.

## Architecture Overview

```
Browser
  │
  ├── Admin Portal (:5001)  ──┐
  └── Member Portal (:5002) ──┤
                               │
                        Gateway / nginx (:8808)
                               │
                        DHService API (FastAPI)
                               │
                        PostgreSQL / TimescaleDB (:5432)
                               │
                        triggers + pg_notify
                               │
                        DHDispatcher
                               │
              ┌────────────────┼────────────────┐
              │                │                │
         DHIdentity       DHAccess         DHStatus
              │                │
           DH2AD           DH2RFID
         [DEV_MODE]       [DEV_MODE]
        (no-op in dev)   (no-op in dev)
```

## Pulling the Latest Changes

If you already have a copy of the repo and want to update it:

```bash
cd deepharbor
git pull origin dev
./dh_dev.sh start
```

That's it — `git pull` downloads the latest code and `dh_dev.sh start`
rebuilds everything so your local environment matches.

If git complains about conflicts with your local edits, stash them
first, pull, then restore:

```bash
git stash
git pull origin dev
git stash pop
```

If the pull included database changes (someone will mention this in
the PR or commit message), do a full reset instead of `start`:

```bash
./dh_dev.sh reset
```

## Troubleshooting

**Containers keep restarting**

Check logs: `docker compose -f docker-compose.yaml -f docker-compose.dev.yml logs -f`

Common causes:
- Missing `config.ini` files — run `./dh_dev.sh setup`
- Missing seed data — run `tools/seed_data.sh generate`
- Port conflicts — check if 5001, 5002, 5432, 8808, or 3300 are in use

**Database not seeding**

The seed data only loads on first boot. If the volume already exists,
init scripts are skipped:

```bash
./dh_dev.sh reset    # removes volumes, re-seeds on next start
```

**Auth bypass not working**

If you see the Azure B2C login page instead of the dev user picker,
the portals are running without the dev compose override. Make sure
you're using both compose files:

```bash
docker compose -f docker-compose.yaml -f docker-compose.dev.yml up --build -d
```

Or just use `./dh_dev.sh start`.

**Worker errors in logs**

DH2AD and DH2RFID have `DEV_MODE=true` set, which should bypass
hardware calls. If you see errors in their logs, they're non-blocking —
the dispatcher marks changes as processed regardless.
