# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "faker>=33.0.0",
# ]
# ///
"""
Generate seed data SQL for the Deep Harbor CRM database.

Produces INSERT statements for the member table with realistic
fictional data. Always includes 10 hardcoded "dev bypass" users
(IDs 1-11) first, then generates additional random members.

The random members mirror the distributions/quirks documented in
pg/tools/SEED_DATA_SPEC.md so local dev/testing exercises the same
realities as the live system (suspended-heavy status, level families,
cohort A/B key splits, format jitter, dead fields, type drift, etc.).

Usage:
    uv run pg/tools/generate_seed_data.py
    uv run pg/tools/generate_seed_data.py --seed abc123 --count 50
    uv run pg/tools/generate_seed_data.py --count 100 --output pg/sql/seed_data.sql
"""

import argparse
import hashlib
import json
import random
import secrets
import string
import sys
from datetime import date, datetime, timedelta

from faker import Faker

# Fixed reference "now" so output depends only on --seed, never wall-clock time.
# (Faker's "today"/"now" anchors read the system clock and break reproducibility.)
REF_DATE = date(2026, 6, 1)
REF_DT = datetime(2026, 6, 1)


def _rand_date(fake: Faker, days_start: int, days_end: int):
    """A date between REF_DATE - days_start and REF_DATE - days_end (deterministic)."""
    return fake.date_between_dates(REF_DATE - timedelta(days=days_start), REF_DATE - timedelta(days=days_end))


def _rand_dt(fake: Faker, days_start: int, days_end: int):
    """A datetime between REF_DT - days_start and REF_DT - days_end (deterministic)."""
    return fake.date_time_between_dates(REF_DT - timedelta(days=days_start), REF_DT - timedelta(days=days_end))


def _rand_time() -> str:
    """A deterministic HH:MM:SS string (Faker's time_object() reads the wall clock)."""
    return f"{random.randint(0, 23):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"


### Lookup data

# Membership-level families — see SEED_DATA_SPEC.md "status.membership_level".
# Free-form strings (not an enum); the zDEFUNCT prefix is a real sorting hack.
ZDEFUNCT_LEVELS = [
    "zDEFUNCT - Member",
    "zDEFUNCT - Member w/ Storage",
    "zDEFUNCT - Volunteer w/ Paid Storage",
]
STRIPE_LEVELS = [
    "Stripe Member - $65",
    "Stripe Member w/ Storage - $95",
    "Stripe Volunteer w/ Paid Storage - $30",
]
PAYPAL_LEVELS = [
    "Member - PayPal",
    "Member w/ Storage - PayPal",
]
WA_ERA_LEVELS = [
    "Membership",
    "New Member",
    "Membership with Storage",
    "Member - Cash Payment",
    "Member - Grandfathered Price",
]
ROLE_BASED_LEVELS = [
    "Volunteer",
    "Board Member / Officer",
    "Area Host",
    "Club Host",
    "Scholarship",
    "Contractor",
    "Volunteer w/ Storage",
]

# requires_login=true — these go in "computer_authorizations"
COMPUTER_AUTHORIZATIONS = [
    "Boss Authorized Users",
    "CNC Plasma Authorized Users",
    "Epilog Authorized Users",
    "ShopBot Authorized Users",
    "Tormach Authorized Users",
    "Universal Authorized Users",
    "Vinyl Cutter Authorized Users",
    "Mimaki CJV30 printer Users",
    "Laser Cutter Authorized Users",
    "Resin Printer Authorized Users",
]

# requires_login=false — these go in "authorizations"
PHYSICAL_AUTHORIZATIONS = [
    "Band Saw",
    "Billiards",
    "Blacksmithing",
    "Bridgeport Mill",
    "Button sewing machines",
    "Clausing Lathe",
    "Coffee Roaster",
    "Cold Metals Basic",
    "Drum Sander",
    "Ender 3D Printers",
    "Formlabs Form 3 printer",
    "Hand held plasma cutter",
    "Jointer",
    "LeBlond Lathe",
    "Metal Band Saw",
    "Metal Drill Press",
    "Mig Welders",
    "Mitre Saw",
    "Multi-Router",
    "Panel Saw",
    "Planer",
    "Pneumatic Power Tools",
    "Powder Coating Equipment",
    "Prusa 3D printers",
    "Router Table",
    "Sanders",
    "Saw Dado",
    "Serger sewing machine",
    "Square Chisel Morticer",
    "Surface Grinder",
    "Table Saw",
    "Tier one Sewing Machine",
    "Tig Welders",
    "Tube Bending Equipment",
    "Wood Drill Press",
    "Wood Lathe",
    "Wood Mini Lathe",
]

# Long, realistic-looking email domains — member emails skew long (48-89 chars).
LONG_EMAIL_DOMAINS = [
    "students.northwestern-university.edu",
    "alumni.illinois-institute-of-technology.edu",
    "consulting.global-partners-chicago.com",
    "engineering.midwest-manufacturing-co.com",
    "mail.independent-contractors-guild.org",
    "fastmail-personal-accounts.com",
    "proton-secure-personal-mail.com",
    "gmail.com",
    "outlook.com",
    "yahoo.com",
]

PRONOUN_VALUES = ["she/her", "he/him", "they/them", "she/they", "he/they", "any/all"]

NOTE_AUTHORS = ["System", "Board", "Admin"]


### Dev bypass users — fixed login fixtures, always emitted first (IDs 1-11).
### They span every member status and all 7 roles (one login per role) so the
### dev-login pages cover the full range of account types. Profiles are clean and
### recognizable; the realistic quirks live on the random members. notes are bare
### JSONB arrays of {timestamp, from, note} to match the dev schema.

DEV_USERS = [
    # ID 1 - Ada Lovelace — active, Administrator (full admin incl. API Clients)
    {
        "identity": {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "nickname": "enchantress_of_numbers",
            "active_directory_username": "alovelace",
            "emails": [{"type": "primary", "email_address": "ada.lovelace@example.com"}],
            "birthday": "1985-12-10",
        },
        "connections": {"discord_handle": "ada_admin", "phone": "3125550101"},
        "status": {
            "membership_status": "active",
            "membership_level": "Membership",
            "member_since": "2020-01-15",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-1234",
            "waiver_signed_date": "2020-01-15",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2020-01-22",
        },
        "access": {"rfid_tags": ["1012345678", "1087654321"]},
        "authorizations": {
            "authorizations": [
                "Table Saw", "Band Saw", "Mig Welders", "Tig Welders",
                "Jointer", "Planer", "Mitre Saw", "Sanders",
                "Wood Drill Press", "Router Table",
            ],
            "computer_authorizations": [
                "Epilog Authorized Users", "Tormach Authorized Users",
                "ShopBot Authorized Users",
            ],
        },
        "extras": {"storage_area": "A01"},
        "notes": [
            {"timestamp": "2020-01-22", "from": "System", "note": "Completed orientation and safety training"},
            {"timestamp": "2023-06-10", "from": "Board", "note": "Granted administrator access to the admin portal"},
        ],
    },
    # ID 2 - Laika Sputnik — active, CTO (full admin incl. API Clients)
    {
        "identity": {
            "first_name": "Laika",
            "last_name": "Sputnik",
            "nickname": "good_dog",
            "active_directory_username": "lsputnik",
            "emails": [{"type": "primary", "email_address": "laika.sputnik@example.com"}],
            "birthday": "1988-11-03",
        },
        "connections": {"discord_handle": "cto_laika", "phone": "3125550102"},
        "status": {
            "membership_status": "active",
            "membership_level": "Stripe Member - $65",
            "member_since": "2019-02-01",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-2002",
            "waiver_signed_date": "2019-02-01",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2019-02-08",
        },
        "access": {"rfid_tags": ["1023456789"]},
        "authorizations": {
            "authorizations": ["Table Saw", "Band Saw", "Ender 3D Printers"],
            "computer_authorizations": ["Epilog Authorized Users", "Tormach Authorized Users"],
        },
        "extras": None,
        "notes": [
            {"timestamp": "2019-02-08", "from": "System", "note": "Completed orientation"},
            {"timestamp": "2022-05-01", "from": "Board", "note": "Appointed CTO"},
        ],
    },
    # ID 3 - Grace Hopper — active, Board (broad admin, no API Clients)
    {
        "identity": {
            "first_name": "Grace",
            "last_name": "Hopper",
            "nickname": "queen_bug",
            "active_directory_username": "ghopper",
            "emails": [{"type": "primary", "email_address": "grace.hopper@example.com"}],
            "birthday": "1972-12-09",
        },
        "connections": {"discord_handle": "admiral_grace", "phone": "3125550103"},
        "status": {
            "membership_status": "active",
            "membership_level": "Board Member / Officer",
            "member_since": "2017-11-01",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-7890",
            "waiver_signed_date": "2017-11-01",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2017-11-08",
        },
        "access": {"rfid_tags": ["1099887766"]},
        "authorizations": {
            "authorizations": ["Ender 3D Printers", "Prusa 3D printers", "Band Saw"],
            "computer_authorizations": [],
        },
        "extras": None,
        "notes": [
            {"timestamp": "2017-11-08", "from": "System", "note": "Completed orientation"},
            {"timestamp": "2022-01-01", "from": "Board", "note": "Elected to board of directors"},
        ],
    },
    # ID 4 - Marie Curie — active, Authorizer (narrow: authorizations/notes)
    {
        "identity": {
            "first_name": "Marie",
            "last_name": "Curie",
            "nickname": "glow_girl",
            "active_directory_username": "mcurie",
            "emails": [{"type": "primary", "email_address": "marie.curie@example.com"}],
            "birthday": "1981-11-07",
        },
        "connections": {"discord_handle": "mcurie_rad", "phone": "3125550104"},
        "status": {
            "membership_status": "active",
            "membership_level": "Volunteer",
            "member_since": "2018-06-01",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-4567",
            "waiver_signed_date": "2018-06-01",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2018-06-08",
        },
        "access": {"rfid_tags": ["1033445566"]},
        "authorizations": {
            "authorizations": [
                "Table Saw", "Band Saw", "Mig Welders", "Tig Welders",
                "Cold Metals Basic", "Metal Band Saw", "Surface Grinder",
            ],
            "computer_authorizations": ["CNC Plasma Authorized Users"],
        },
        "extras": None,
        "notes": [
            {"timestamp": "2018-06-08", "from": "System", "note": "Completed orientation"},
            {"timestamp": "2019-02-14", "from": "Board", "note": "Approved as equipment authorizer for metalworking"},
        ],
    },
    # ID 5 - Rosalind Franklin — active, ID Check (onboarder workflow)
    {
        "identity": {
            "first_name": "Rosalind",
            "last_name": "Franklin",
            "nickname": "photo_51",
            "active_directory_username": "rfranklin",
            "emails": [{"type": "primary", "email_address": "rosalind.franklin@example.com"}],
            "birthday": "1995-07-25",
        },
        "connections": {"discord_handle": "xray_rosalind", "phone": "3125550105"},
        "status": {
            "membership_status": "active",
            "membership_level": "Membership with Storage",
            "member_since": "2021-04-01",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-6789",
            "waiver_signed_date": "2021-04-01",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2021-04-08",
        },
        "access": {"rfid_tags": ["1033221100", "1044332211"]},
        "authorizations": {
            "authorizations": [
                "Table Saw", "Band Saw", "Mig Welders", "Jointer",
                "Planer", "Ender 3D Printers", "Prusa 3D printers",
            ],
            "computer_authorizations": [
                "Epilog Authorized Users", "Tormach Authorized Users",
            ],
        },
        "extras": {"storage_area": "B12"},
        "notes": [
            {"timestamp": "2021-04-08", "from": "System", "note": "Completed orientation and basic woodshop training"},
            {"timestamp": "2022-08-19", "from": "Board", "note": "Approved as ID-check onboarder"},
        ],
    },
    # ID 6 - Margaret Hamilton — active, Treasurer (narrow: identity/status/roles)
    {
        "identity": {
            "first_name": "Margaret",
            "last_name": "Hamilton",
            "nickname": "stack_overflow",
            "active_directory_username": "mhamilton",
            "emails": [{"type": "primary", "email_address": "margaret.hamilton@example.com"}],
            "birthday": "1986-08-17",
        },
        "connections": {"discord_handle": "mhamilton_apollo", "phone": "3125550106"},
        "status": {
            "membership_status": "active",
            "membership_level": "Membership",
            "member_since": "2018-03-15",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-2345",
            "waiver_signed_date": "2018-03-15",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2018-03-22",
        },
        "access": {"rfid_tags": ["1077665544"]},
        "authorizations": {
            "authorizations": ["Table Saw", "Mitre Saw", "Sanders", "Ender 3D Printers"],
            "computer_authorizations": ["Epilog Authorized Users"],
        },
        "extras": None,
        "notes": [
            {"timestamp": "2018-03-22", "from": "System", "note": "Completed orientation"},
            {"timestamp": "2023-01-01", "from": "Board", "note": "Appointed treasurer"},
        ],
    },
    # ID 7 - Hedy Lamarr — active, Area Host
    {
        "identity": {
            "first_name": "Hedy",
            "last_name": "Lamarr",
            "nickname": "frequency_hopper",
            "active_directory_username": "hlamarr",
            "emails": [{"type": "primary", "email_address": "hedy.lamarr@example.com"}],
            "birthday": "1980-11-09",
        },
        "connections": {"discord_handle": "hedy_builds", "phone": "3125550107"},
        "status": {
            "membership_status": "active",
            "membership_level": "Area Host",
            "member_since": "2019-09-15",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-3456",
            "waiver_signed_date": "2019-09-15",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2019-09-22",
        },
        "access": {"rfid_tags": ["1044556677", "1055667788"]},
        "authorizations": {
            "authorizations": [
                "Table Saw", "Band Saw", "Wood Lathe", "Drum Sander",
                "Panel Saw", "Jointer", "Planer", "Ender 3D Printers",
                "Prusa 3D printers", "Formlabs Form 3 printer",
            ],
            "computer_authorizations": [
                "Epilog Authorized Users", "Vinyl Cutter Authorized Users",
                "Mimaki CJV30 printer Users",
            ],
        },
        "extras": {"storage_area": "C05"},
        "notes": [
            {"timestamp": "2019-09-22", "from": "System", "note": "Completed orientation and all woodshop authorizations"},
            {"timestamp": "2020-04-01", "from": "Board", "note": "Approved as area host for woodshop and 3D printing"},
        ],
    },
    # ID 8 - Katherine Johnson — active, no role (cohort B forms; admin lockout test)
    {
        "identity": {
            "first_name": "Katherine",
            "last_name": "Johnson",
            "nickname": "human_computer",
            "active_directory_username": "kjohnson",
            "emails": [{"type": "primary", "email_address": "katherine.johnson@example.com"}],
            "birthday": "1990-08-26",
        },
        "connections": {"discord_handle": "kjohnson_math", "phone": "3125550108"},
        "status": {
            "membership_status": "active",
            "membership_level": "Stripe Member - $65",
            "member_since": "2024-02-14",
            "waiver_signed": True,
        },
        "forms": {
            "id_check_date": "2024-02-14",
            "id_check_by": 5,
            "is_21_or_older": True,
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "essentials_forms_completed_date": "",
            "waiver_signed_at": "",
        },
        "access": {"rfid_tags": ["1066778899"]},
        "authorizations": {
            "authorizations": [
                "Ender 3D Printers", "Prusa 3D printers",
                "Formlabs Form 3 printer", "Tier one Sewing Machine",
                "Serger sewing machine", "Button sewing machines",
            ],
            "computer_authorizations": [
                "Epilog Authorized Users", "Vinyl Cutter Authorized Users",
            ],
        },
        "extras": {"storage_area": ""},
        "notes": [
            {"timestamp": "2024-02-21", "from": "System", "note": "Completed orientation, focused on textiles and 3D printing"},
        ],
    },
    # ID 9 - Dorothy Vaughan — pending, minimal data (onboard flow, cohort B)
    {
        "identity": {
            "first_name": "Dorothy",
            "last_name": "Vaughan",
            "nickname": None,
            "active_directory_username": "dvaughan",
            "emails": [{"type": "primary", "email_address": "dorothy.vaughan@example.com"}],
            "birthday": "1999-09-20",
        },
        "connections": {"discord_handle": "", "phone": ""},
        "status": {
            "membership_status": "pending",
            "membership_level": "New Member",
            "member_since": "2026-05-28",
        },
        "forms": None,
        "access": None,
        "authorizations": None,
        "extras": None,
        "notes": None,
    },
    # ID 10 - Charles Babbage — suspended (zDEFUNCT level; locked keys card)
    {
        "identity": {
            "first_name": "Charles",
            "last_name": "Babbage",
            "nickname": "difference_engine",
            "active_directory_username": "cbabbage",
            "emails": [{"type": "primary", "email_address": "charles.babbage@example.com"}],
            "birthday": "1978-04-22",
        },
        "connections": {"discord_handle": "cbabbage", "phone": "3125550110"},
        "status": {
            "membership_status": "suspended",
            "membership_level": "zDEFUNCT - Member",
            "member_since": "2019-03-10",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "DL-5678",
            "waiver_signed_date": "2019-03-10",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2019-03-17",
        },
        "access": {"rfid_tags": ["1011223344"]},
        "authorizations": {
            "authorizations": [
                "Table Saw", "Band Saw", "Metal Band Saw",
                "Metal Drill Press", "Bridgeport Mill", "Clausing Lathe",
            ],
            "computer_authorizations": ["Boss Authorized Users"],
        },
        "extras": None,
        "notes": [
            {"timestamp": "2019-03-17", "from": "System", "note": "Orientation completed"},
            {"timestamp": "2024-03-01", "from": "System", "note": "Membership lapsed — moved to suspended"},
        ],
    },
    # ID 11 - Nikola Tesla — banned (/dashboard/locked lockout)
    {
        "identity": {
            "first_name": "Nikola",
            "last_name": "Tesla",
            "nickname": "spark_lord",
            "active_directory_username": "ntesla",
            "emails": [{"type": "primary", "email_address": "nikola.tesla@example.com"}],
            "birthday": "1992-07-09",
        },
        "connections": {"discord_handle": "spark_lord", "phone": "3125550111"},
        "status": {
            "membership_status": "banned",
            "membership_level": "Membership",
            "member_since": "2018-06-01",
        },
        "forms": {
            "id_check_1": "IL",
            "id_check_2": "PP-9012",
            "waiver_signed_date": "2018-06-01",
            "terms_of_use_accepted": True,
            "essentials_form": "completed",
            "orientation_completed_date": "2018-06-08",
        },
        "access": {"rfid_tags": ["1055667799"]},
        "authorizations": {
            "authorizations": ["Table Saw", "Band Saw", "Tig Welders"],
            "computer_authorizations": [],
        },
        "extras": None,
        "notes": [
            {"timestamp": "2018-06-08", "from": "System", "note": "Completed orientation"},
            {"timestamp": "2024-09-12", "from": "Board", "note": "Banned — repeated code of conduct violations"},
        ],
    },
]

# RFID tags / usernames / emails used by dev users — tracked so the generator
# doesn't accidentally duplicate them in random members.
DEV_USER_RFID_TAGS = set()
DEV_USER_USERNAMES = set()
DEV_USER_EMAILS = set()
for _user in DEV_USERS:
    if _user.get("access") and _user["access"].get("rfid_tags"):
        DEV_USER_RFID_TAGS.update(_user["access"]["rfid_tags"])
    if _user["identity"].get("active_directory_username"):
        DEV_USER_USERNAMES.add(_user["identity"]["active_directory_username"].lower())
    for email_entry in _user["identity"].get("emails", []):
        DEV_USER_EMAILS.add(email_entry["email_address"].lower())


### SQL generation helpers

def make_member_sql(member: dict) -> str:
    """Convert a member dict to an INSERT INTO member (...) VALUES (...) statement."""
    columns = [
        "identity", "connections", "status", "forms",
        "access", "authorizations", "extras", "notes",
    ]

    values = []
    for col in columns:
        val = member.get(col)
        if val is None:
            values.append("NULL")
        else:
            json_str = json.dumps(val, ensure_ascii=False)
            escaped = json_str.replace("'", "''")
            values.append(f"'{escaped}'::jsonb")

    cols_str = ", ".join(columns)
    vals_str = ",\n    ".join(values)
    return f"INSERT INTO member ({cols_str}) VALUES (\n    {vals_str}\n);"


### Value helpers (see SEED_DATA_SPEC.md for the target distributions)

def _alnum(n: int) -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def make_long_email(fake: Faker, used_emails: set) -> str:
    """Generate a long (48-89 char), case-insensitively unique email address."""
    for _ in range(2000):
        words = [w.lower() for w in fake.words(nb=random.randint(2, 3))]
        local = ".".join(words)
        if random.random() < 0.5:
            local += str(random.randint(1, 99999))
        email = f"{local}@{random.choice(LONG_EMAIL_DOMAINS)}"
        if 48 <= len(email) <= 89 and email.lower() not in used_emails:
            used_emails.add(email.lower())
            return email
    # Fallback — guarantee uniqueness/length even if sampling kept colliding.
    email = f"{_alnum(40).lower()}@fastmail-personal-accounts.com"
    used_emails.add(email.lower())
    return email


def make_phone() -> str:
    """Phone with realistic format jitter; ~78% bare-10 / ~11% empty / etc."""
    r = random.random()
    if r < 0.78:
        return f"{random.randint(2, 9)}{random.randint(0, 999999999):09d}"
    if r < 0.89:
        return ""
    if r < 0.97:
        return f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"
    if r < 0.98:
        return f"+1{random.randint(2000000000, 9999999999)}"
    if r < 0.988:
        return f"{random.randint(200, 999)} {random.randint(200, 999)} {random.randint(1000, 9999)}"
    if r < 0.993:
        return f"{random.randint(200, 999)}.{random.randint(200, 999)}.{random.randint(1000, 9999)}"
    if r < 0.997:
        return f"({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}"
    return f"{random.randint(100000000, 999999999)}"  # broken 9-digit (data-quality bug)


def make_birthday(fake: Faker) -> str | None:
    """~99% bare ISO date (YYYY-MM-DD) / ~1% null.

    Birthdays are canonical bare ISO dates (matching the post-#285 prod state).
    The ~1% null cohort is legitimate "no birthday on file". The legacy 19-char
    naive-datetime form (Wild Apricot import) is no longer emitted.
    """
    d = _rand_date(fake, 70 * 365, 18 * 365)  # 18-70 years old vs REF_DATE
    if random.random() < 0.01:
        return None
    return d.isoformat()


def make_member_since(fake: Faker, cohort_b: bool) -> str | None:
    """Cohort B persists date-only; cohort A is TZ-aware datetime / null / empty."""
    d = _rand_date(fake, 8 * 365, 30)
    if cohort_b:
        return d.isoformat()
    r = random.random()
    if r < 0.06:
        return None
    if r < 0.08:
        return ""
    return f"{d.isoformat()}T{_rand_time()}+00:00"


def make_renewal_date(fake: Faker) -> str | None:
    """Naive datetime (19-char) / null / empty — mostly stale or absent."""
    r = random.random()
    if r < 0.47:
        return None
    if r < 0.54:
        return ""
    d = _rand_date(fake, 6 * 365, 365)
    return f"{d.isoformat()}T{_rand_time()}"


def make_balance():
    """~97% zero / ~2% small positive / ~1% small negative; ~4% encoded as string."""
    r = random.random()
    if r < 0.967:
        val = 0
    elif r < 0.987:
        val = round(random.uniform(0.5, 50), 2)
    else:
        val = -round(random.uniform(0.5, 50), 2)
    return str(val) if random.random() < 0.04 else val


def make_donations():
    """Dead field — always 0, with the same number/string encoding drift."""
    return "0" if random.random() < 0.04 else 0


def make_wildapricot_id(used: set) -> int:
    """8-digit unique JSON-number contact id (cohort A)."""
    for _ in range(10000):
        wid = random.randint(10000000, 99999999)
        if wid not in used:
            used.add(wid)
            return wid
    return random.randint(10000000, 99999999)


def make_cus_id() -> str:
    return f"cus_{_alnum(14)}"


def pick_membership_level(status: str) -> tuple[str | None, str]:
    """Return (level, family) honoring the status<->level coupling rules."""
    if status == "pending":
        return random.choice(["New Member", "Membership"]), "wa"
    if status == "suspended":
        fam = random.choices(
            ["zdefunct", "stripe", "wa", "paypal", "blank", "role"],
            weights=[55, 18, 9, 5, 8, 5], k=1,
        )[0]
    elif status == "active":
        fam = random.choices(
            ["stripe", "wa", "role", "paypal"],
            weights=[64, 26, 7, 3], k=1,
        )[0]
    elif status == "banned":
        fam = random.choices(
            ["wa", "blank", "stripe", "role"],
            weights=[40, 40, 12, 8], k=1,
        )[0]
    else:  # inactive (valid but unused in practice)
        fam = "wa"

    if fam == "zdefunct":
        return random.choice(ZDEFUNCT_LEVELS), fam
    if fam == "stripe":
        return random.choice(STRIPE_LEVELS), fam
    if fam == "paypal":
        return random.choice(PAYPAL_LEVELS), fam
    if fam == "role":
        return random.choice(ROLE_BASED_LEVELS), fam
    if fam == "blank":
        return ("" if random.random() < 0.9 else None), fam
    return random.choice(WA_ERA_LEVELS), fam


### ID-check data: dev seed exercises every cell of the new/legacy matrix so the
### admin Forms tab and member-portal Forms card can be tested without hand-tooling
### DB UPDATEs.

# Cell distribution for randomly-generated members with forms populated.
ID_CHECK_CELL_WEIGHTS = {
    "legacy_only": 60,
    "new_only": 17,
    "both": 17,
    "empty": 6,
}

# Member IDs holding a role that grants `member.forms` change (per ROLE_ASSIGNMENTS).
# id_check_by picks bias toward these onboarders, but occasionally select a
# non-onboarder so the post-save soft-warning render path gets exercised.
_ONBOARDER_IDS = (1, 2, 3, 5, 7)  # Administrator/CTO/Board/ID Check/Area Host (grant member.forms change)
_NON_ONBOARDER_IDS = (4, 6)       # Authorizer/Treasurer (no forms change)


def _pick_id_check_by() -> int:
    """Pick a member_id for `id_check_by`, biased toward onboarders."""
    if random.random() < 0.85:
        return random.choice(_ONBOARDER_IDS)
    return random.choice(_NON_ONBOARDER_IDS)


def _legacy_id_check_pair(fake: Faker) -> tuple[str, str]:
    """Return a (id_check_1, id_check_2) pair from one of the historical "eras"
    of inconsistent free-form usage. Empty strings are valid: many real records
    had only one of the two fields populated."""
    pattern = random.choice([
        "default",         # IL + DL-NNNN
        "verbose_state",   # Illinois + D123-4567-8901
        "passport",        # US + PP-NNNNNNNN
        "free_form",       # initials + verification date in id_check_2
        "single_combined", # everything in id_check_1, id_check_2 empty
        "rambling",        # narrative note in both
    ])
    if pattern == "default":
        return fake.state_abbr(), f"DL-{random.randint(1000, 9999)}"
    if pattern == "verbose_state":
        return fake.state(), f"D{random.randint(100, 999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
    if pattern == "passport":
        return "US", f"PP-{fake.bothify('?########').upper()}"
    if pattern == "free_form":
        initials = fake.first_name()[0] + fake.last_name()[0]
        verify_date = _rand_date(fake, 7 * 365, 2 * 365).isoformat()
        return initials, verify_date
    if pattern == "single_combined":
        return f"{fake.state_abbr()} DL {fake.bothify('?#######').upper()}", ""
    return f"saw {fake.state_abbr()} DL, looked legit", f"{fake.first_name()[0]}{fake.last_name()[0]} approved"


def generate_forms(fake: Faker, cohort_b: bool) -> dict:
    """Generate a forms JSONB object, with cohort-A vs cohort-B key sets.

    Cohort A: essentials_form_completed_date (singular), waiver_signed_date,
              covid_vaccine_policy_acknowledged.
    Cohort B: essentials_forms_completed_date (plural, dead), waiver_signed_at
              (dead), is_21_or_older.
    The ID-check matrix + the dev-only `essentials_form` key + terms apply to both.
    """
    forms = {
        "terms_of_use_accepted": True,
        "essentials_form": "completed",
    }

    # ID-check matrix cell (shared by both cohorts).
    cells = list(ID_CHECK_CELL_WEIGHTS.keys())
    weights = [ID_CHECK_CELL_WEIGHTS[c] for c in cells]
    cell = random.choices(cells, weights=weights, k=1)[0]
    if cell in ("legacy_only", "both"):
        legacy1, legacy2 = _legacy_id_check_pair(fake)
        forms["id_check_1"] = legacy1
        forms["id_check_2"] = legacy2
    if cell in ("new_only", "both"):
        forms["id_check_date"] = _rand_date(fake, 5 * 365, 0).isoformat()
        forms["id_check_by"] = _pick_id_check_by()

    # Orientation (~9% of cohort A; cohort B doesn't track it here).
    if not cohort_b and random.random() < 0.09:
        forms["orientation_completed_date"] = (
            f"{_rand_date(fake, 5 * 365, 30).isoformat()}T00:00:00"
        )

    if cohort_b:
        # Cohort B renamed date fields are dead (always empty/null).
        forms["essentials_forms_completed_date"] = "" if random.random() < 0.7 else None
        forms["waiver_signed_at"] = "" if random.random() < 0.7 else None
        forms["is_21_or_older"] = True
    else:
        # waiver_signed_date populated on ~53% of cohort A.
        if random.random() < 0.53:
            forms["waiver_signed_date"] = (
                f"{_rand_date(fake, 6 * 365, 30).isoformat()}T00:00:00"
            )
        else:
            forms["waiver_signed_date"] = None
        # essentials_form_completed_date populated on ~2%.
        if random.random() < 0.02:
            forms["essentials_form_completed_date"] = (
                f"{_rand_date(fake, 6 * 365, 30).isoformat()}T00:00:00"
            )
        # covid field — deprecated, populated on a minority as an inert string.
        forms["covid_vaccine_policy_acknowledged"] = (
            _rand_date(fake, 4 * 365, 2 * 365).isoformat()
            if random.random() < 0.14 else None
        )

    return forms


def generate_unique_rfid_tags(count: int, used_tags: set) -> list[str]:
    """Generate ~10-digit numeric RFID tags, unique, with occasional empties/longer.

    Tags are digit-only: the access reader stores them as numbers and lpads to
    10 digits on read (never hex)."""
    tags = []
    for _ in range(count):
        if random.random() < 0.005:
            tags.append("")  # data-quality bug: empty tag
            continue
        for _attempt in range(1000):
            length = 10 if random.random() > 0.03 else random.randint(20, 38)
            tag = "".join(random.choice("0123456789") for _ in range(length))
            if tag and tag not in used_tags:
                used_tags.add(tag)
                tags.append(tag)
                break
    return tags


def generate_authorizations() -> dict | None:
    """Heavily zero-inflated authorization sets from the fixed pools."""
    num_physical = random.choices(
        [0, 1, 2, 3, 5, 7, 10, 15, 25],
        weights=[70, 8, 6, 5, 4, 3, 2, 1, 1], k=1,
    )[0]
    num_computer = random.choices(
        [0, 1, 2, 3, 5],
        weights=[73, 12, 8, 4, 3], k=1,
    )[0]

    physical = sorted(random.sample(PHYSICAL_AUTHORIZATIONS, min(num_physical, len(PHYSICAL_AUTHORIZATIONS))))
    computer = sorted(random.sample(COMPUTER_AUTHORIZATIONS, min(num_computer, len(COMPUTER_AUTHORIZATIONS))))

    return {"authorizations": physical, "computer_authorizations": computer}


def _note_count() -> int:
    """avg ~1.86, median 1, p95 5, max 11."""
    return random.choices(
        [1, 2, 3, 4, 5, 6, 7, 8, 11],
        weights=[50, 25, 12, 6, 4, 1.2, 0.8, 0.6, 0.4], k=1,
    )[0]


def _make_timestamp(fake: Faker) -> str:
    return _rand_dt(fake, 4 * 365, 0).strftime("%Y-%m-%dT%H:%M:%S")


def generate_notes(fake: Faker) -> list:
    """Bare array of {timestamp, from, note}; ~1.5% are timestamp-only stubs."""
    notes = []
    for _ in range(_note_count()):
        if random.random() < 0.015:
            notes.append({"timestamp": _make_timestamp(fake)})
        else:
            notes.append({
                "timestamp": _make_timestamp(fake),
                "from": random.choice(NOTE_AUTHORS),
                "note": fake.sentence(nb_words=random.randint(5, 15)),
            })
    return notes


def generate_random_member(
    fake: Faker,
    used_rfid_tags: set,
    used_usernames: set,
    used_emails: set,
    used_wa_ids: set,
) -> dict:
    """Generate a single randomized member dict per SEED_DATA_SPEC.md."""
    # Status mix: ~73% suspended / 25% active / 1% pending / <1% banned.
    membership_status = random.choices(
        ["suspended", "active", "pending", "banned"],
        weights=[73, 25, 1, 0.6], k=1,
    )[0]
    is_active = membership_status == "active"
    is_pending = membership_status == "pending"
    is_new = is_active and random.random() < 0.08
    has_full_data = not is_new and not is_pending

    # Cohort A (~95%, WA migration) vs B (~5%, post-migration). Pending members
    # are native (cohort B) signups.
    cohort_b = is_pending or random.random() < 0.05

    first_name = fake.first_name()
    last_name = fake.last_name()

    # Unique username (case-insensitive).
    username = f"{first_name[0].lower()}{last_name.lower()}"
    base_username, counter = username, 1
    while username.lower() in used_usernames:
        username = f"{base_username}{counter}"
        counter += 1

    email = make_long_email(fake, used_emails)

    if has_full_data:
        used_usernames.add(username.lower())

    # --- identity ---
    birthday = make_birthday(fake)
    # nickname: ~14% real / ~78% null / rest empty
    nr = random.random()
    nickname = fake.user_name() if nr < 0.14 else ("" if nr < 0.22 else None)
    # AD username: ~98.4% present, ~1.6% null/empty
    ar = random.random()
    ad_username = username if has_full_data else None
    if ad_username is not None and ar < 0.016:
        ad_username = None if random.random() < 0.7 else ""

    identity = {
        "first_name": first_name,
        "last_name": last_name,
        "nickname": nickname if has_full_data else None,
        "active_directory_username": ad_username,
        "emails": [{"type": "primary", "email_address": email}],
        "birthday": birthday,
    }
    # aliases: dead [] on ~92%, key omitted on ~8%
    if random.random() < 0.92:
        identity["aliases"] = []
    # pronouns: ~6% opt-in, ~50/50 populated/empty
    if random.random() < 0.06:
        identity["pronouns"] = random.choice(PRONOUN_VALUES) if random.random() < 0.5 else ""
    # member_id + primary_email opt-in cohort (~6%); member_id is a JSON number.
    if has_full_data and random.random() < 0.06:
        identity["member_id"] = random.randint(1, 9999)
        identity["primary_email"] = email
    # nametag / theme-song opt-in cohort (~5%); theme_song_duration is a STRING.
    if has_full_data and random.random() < 0.05:
        if random.random() < 0.13:
            identity["nametag_subtitle"] = fake.catch_phrase()[:40]
        if random.random() < 0.06:
            identity["theme_song_url"] = f"https://www.youtube.com/watch?v={_alnum(11)}"
            identity["theme_song_duration"] = str(random.randint(30, 320))

    # --- status ---
    membership_level, level_family = pick_membership_level(membership_status)
    member_since = make_member_since(fake, cohort_b)
    status = {
        "membership_status": membership_status,
        "membership_level": membership_level,
        "member_since": member_since,
        "renewal_date": make_renewal_date(fake),
    }
    if not cohort_b:
        # cohort-A financial block
        status["balance"] = make_balance()
        status["donations"] = make_donations()
        status["donor"] = random.random() < 0.05
    else:
        status["waiver_signed"] = random.random() < 0.5

    # Stripe subscription block (status) — coupled sub_/prod_ triple-state, only
    # on a subset, biased to active stripe-tier. Models the "paying-but-no-IDs" gap.
    if level_family == "stripe" and is_active and random.random() < 0.62:
        st = random.random()
        if st < 0.67:
            status["stripe_subscription_id"] = f"sub_{_alnum(24)}"
            status["stripe_product_id"] = f"prod_{_alnum(14)}"
        elif st < 0.99:
            status["stripe_subscription_id"] = None
            status["stripe_product_id"] = None
        else:
            status["stripe_subscription_id"] = ""
            status["stripe_product_id"] = ""

    # --- connections ---
    connections = None
    if has_full_data:
        connections = {
            "discord_handle": fake.user_name() if random.random() < 0.65 else "",
            "phone": make_phone(),
        }
        if not cohort_b:
            connections["wildapricot_id"] = make_wildapricot_id(used_wa_ids)
        # stripe_id / stripe_customer_id overlap (neither/both/cust-only/id-only).
        ov = random.random()
        if ov < 0.63:
            pass
        elif ov < 0.82:
            cid = make_cus_id()
            connections["stripe_customer_id"] = cid
            connections["stripe_id"] = cid if random.random() < 0.98 else make_cus_id()
        elif ov < 0.93:
            connections["stripe_customer_id"] = make_cus_id()
        else:
            connections["stripe_id"] = make_cus_id()

    # --- forms (null if brand new or pending) ---
    forms = generate_forms(fake, cohort_b) if has_full_data else None

    # --- access / rfid (column present for full members; array may be empty) ---
    access = None
    if has_full_data:
        num_tags = random.choices([0, 1, 1, 1, 2, 2, 3, 5], k=1)[0]
        tags = generate_unique_rfid_tags(num_tags, used_rfid_tags) if num_tags > 0 else []
        access = {"rfid_tags": tags}

    # --- authorizations (null if brand new or pending) ---
    authorizations = generate_authorizations() if has_full_data else None

    # --- extras: storage_area 3-state + dead ip_addresses/server_rack_space ---
    extras = None
    if has_full_data:
        sr = random.random()
        if sr < 0.37:
            storage_area = None
        elif sr < 0.96:
            storage_area = ""
        else:
            storage_area = _alnum(random.randint(3, 7)).upper()
        extras = {"storage_area": storage_area}
        if not cohort_b:
            extras["ip_addresses"] = None
            extras["server_rack_space"] = None

    # --- notes (bare array; present for full members, occasionally just a stub) ---
    notes = generate_notes(fake) if has_full_data else None

    if membership_status == "suspended" and (notes is None or random.random() < 0.6):
        lapsed = {
            "timestamp": _make_timestamp(fake),
            "from": "System",
            "note": random.choice([
                "Membership lapsed — moved to suspended",
                "Payment failed — membership suspended",
                "Member requested deactivation",
                "Membership expired — no renewal",
            ]),
        }
        notes = (notes or []) + [lapsed]

    if membership_status == "banned":
        ban = {
            "timestamp": _make_timestamp(fake),
            "from": "Board",
            "note": random.choice([
                "Banned — repeated safety violations",
                "Banned — code of conduct violation",
                "Banned — harassment policy violation",
                "Banned — unauthorized use of equipment",
            ]),
        }
        notes = (notes or []) + [ban]

    return {
        "identity": identity,
        "connections": connections,
        "status": status,
        "forms": forms,
        "access": access,
        "authorizations": authorizations,
        "extras": extras,
        "notes": notes,
        # private generation metadata (stripped before SQL emission)
        "_meta": {"cohort_b": cohort_b, "level_family": level_family},
    }


### Rare-quirk coverage — guarantee each edge case appears even at small N.

def ensure_coverage(members: list, fake: Faker) -> None:
    """Force >=1 instance of each rare edge case, mutating members in place by
    index (deterministic). Logs which cases were injected or skipped."""
    if not members:
        return

    def has_cohort_b(m):
        f = m.get("forms") or {}
        return any(k in f for k in ("essentials_forms_completed_date", "waiver_signed_at", "is_21_or_older")) \
            or "waiver_signed" in (m.get("status") or {})

    def has_null_column(m):
        return any(m.get(c) is None for c in ("connections", "status", "forms", "access", "authorizations", "extras", "notes"))

    def has_string_member_id(m):
        return isinstance(m["identity"].get("member_id"), str)

    def has_corrupt_year(m):
        ms = m["status"].get("member_since")
        return isinstance(ms, str) and ms.startswith("1992")

    def has_empty_rfid(m):
        acc = m.get("access")
        return bool(acc) and "" in acc.get("rfid_tags", [])

    def has_paying_no_ids(m):
        return (
            m["_meta"]["level_family"] == "stripe"
            and m["status"]["membership_status"] == "active"
            and not m["status"].get("stripe_subscription_id")
            and not (m.get("connections") or {}).get("stripe_id")
            and not (m.get("connections") or {}).get("stripe_customer_id")
        )

    def has_blank_level(m):
        return m["status"].get("membership_level") in ("", None)

    def is_full(m):
        # has the secondary columns populated (i.e. not pending/brand-new)
        return m.get("forms") is not None

    def inject_cohort_b(m):
        m["_meta"]["cohort_b"] = True
        m["status"].pop("balance", None)
        m["status"].pop("donations", None)
        m["status"].pop("donor", None)
        m["status"]["waiver_signed"] = True
        m["forms"] = generate_forms(fake, cohort_b=True)
        if m.get("connections"):
            m["connections"].pop("wildapricot_id", None)

    def inject_string_member_id(m):
        m["identity"]["member_id"] = str(random.randint(1, 9999))
        m["identity"].setdefault("primary_email", m["identity"]["emails"][0]["email_address"])

    def inject_paying_no_ids(m):
        m["status"]["membership_status"] = "active"
        m["status"]["membership_level"] = random.choice(STRIPE_LEVELS)
        m["_meta"]["level_family"] = "stripe"
        m["status"].pop("stripe_subscription_id", None)
        m["status"].pop("stripe_product_id", None)
        if m.get("connections"):
            m["connections"].pop("stripe_id", None)
            m["connections"].pop("stripe_customer_id", None)

    injected, skipped, used_idx = [], [], set()

    def pick_idx(eligible):
        for i, m in enumerate(members):
            if i not in used_idx and eligible(m):
                used_idx.add(i)
                return i
        return None

    cases = [
        ("cohort_b", has_cohort_b, is_full, inject_cohort_b),
        ("string_member_id", has_string_member_id, is_full, inject_string_member_id),
        ("corrupt_member_since", has_corrupt_year, is_full,
         lambda m: m["status"].__setitem__("member_since", "1992-04-11T09:30:00+00:00")),
        ("blank_level", has_blank_level, lambda m: True,
         lambda m: m["status"].__setitem__("membership_level", "")),
        ("empty_rfid", has_empty_rfid, is_full, lambda m: m.__setitem__("access", {"rfid_tags": [""]})),
        ("null_column", has_null_column, is_full, lambda m: m.__setitem__("extras", None)),
        ("paying_no_ids", has_paying_no_ids, is_full, inject_paying_no_ids),
    ]

    for name, predicate, eligible, apply in cases:
        if any(predicate(m) for m in members):
            continue
        idx = pick_idx(eligible)
        if idx is None:
            skipped.append(name)
            continue
        apply(members[idx])
        injected.append(f"{name}@idx{idx}")

    if injected:
        print(f"ensure_coverage: injected {', '.join(injected)}", file=sys.stderr)
    if skipped:
        print(f"ensure_coverage: SKIPPED (N too small): {', '.join(skipped)}", file=sys.stderr)


### Role assignment SQL

# Dev-user role assignments (role_id, member_id, name, role_name). Role ids match
# pgsql_schema.sql: 1 Authorizer, 2 Administrator, 3 Board, 4 ID Check, 5 CTO,
# 6 Treasurer, 7 Area Host.
ROLE_ASSIGNMENTS = [
    (2, 1, "Ada Lovelace", "Administrator"),
    (5, 2, "Laika Sputnik", "CTO"),
    (3, 3, "Grace Hopper", "Board"),
    (1, 4, "Marie Curie", "Authorizer"),
    (4, 5, "Rosalind Franklin", "ID Check"),
    (6, 6, "Margaret Hamilton", "Treasurer"),
    (7, 7, "Hedy Lamarr", "Area Host"),
]

# Skew for random role-holders (role_id -> weight). Treasurer (6) unassigned.
RANDOM_ROLE_SKEW = {1: 40, 3: 23, 7: 17, 2: 10, 4: 7, 5: 3}
# Narrow roles allowed for the single suspended-with-role outlier.
NARROW_ROLES = (4, 7, 1)


def assign_random_roles(active_ids: list[int], suspended_ids: list[int], total_random: int) -> list[tuple[int, int]]:
    """Pick ~1% of random members as single-role holders (active-only, spec skew)
    plus one narrow-role suspended outlier. Returns (role_id, member_id) pairs."""
    assignments = []
    n_holders = max(1, round(total_random * 0.01)) if total_random >= 50 else 0
    if not active_ids:
        return assignments

    role_ids = list(RANDOM_ROLE_SKEW.keys())
    role_weights = [RANDOM_ROLE_SKEW[r] for r in role_ids]

    chosen = random.sample(active_ids, min(n_holders, len(active_ids)))
    for mid in chosen:
        role = random.choices(role_ids, weights=role_weights, k=1)[0]
        assignments.append((role, mid))

    # One suspended narrow-role outlier (stale privilege).
    if suspended_ids and n_holders > 0:
        assignments.append((random.choice(NARROW_ROLES), random.choice(suspended_ids)))

    return assignments


def generate_role_assignments_sql(extra_assignments: list[tuple[int, int]]) -> str:
    lines = []
    for role_id, member_id, name, role_name in ROLE_ASSIGNMENTS:
        lines.append(
            f"INSERT INTO member_to_role (role_id, member_id) "
            f"VALUES ({role_id}, {member_id});   /* {name} -> {role_name} */"
        )
    for role_id, member_id in extra_assignments:
        lines.append(
            f"INSERT INTO member_to_role (role_id, member_id) "
            f"VALUES ({role_id}, {member_id});   /* random role-holder */"
        )
    return "\n".join(lines)


### Main SQL generation

def generate_sql(count: int, seed: str) -> str:
    """Generate the complete seed data SQL file."""
    seed_int = int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)
    random.seed(seed_int)
    Faker.seed(seed_int)
    fake = Faker()

    lines = []
    lines.append("/*")
    lines.append(" * Deep Harbor Seed Data (generated)")
    lines.append(" *")
    lines.append(f" * Seed:  {seed}")
    lines.append(f" * Count: {count + len(DEV_USERS)} total ({len(DEV_USERS)} dev users + {count} random)")
    lines.append(" *")
    lines.append(" * Generated by: pg/tools/generate_seed_data.py")
    lines.append(f" * Reproduce with: uv run pg/tools/generate_seed_data.py --seed {seed} --count {count}")
    lines.append(" * Shapes/distributions: see pg/tools/SEED_DATA_SPEC.md")
    lines.append(" *")
    lines.append(f" * IMPORTANT: The first {len(DEV_USERS)} members are dev bypass users with stable IDs.")
    lines.append(" * Issue #13 (dev auth bypass) references these IDs. Don't reorder them.")
    lines.append(" *")
    lines.append(" * Inserting members fires the audit trigger, log_member_changes(),")
    lines.append(" * and pg_notify. First boot will be noisy. This is expected.")
    lines.append(" */")
    lines.append("")

    # Dev users
    lines.append("")
    lines.append("/* =====================================================")
    lines.append(f" * Dev Bypass Users (IDs 1-{len(DEV_USERS)})")
    lines.append(" * ===================================================== */")
    lines.append("")
    for i, user in enumerate(DEV_USERS):
        name = f"{user['identity']['first_name']} {user['identity']['last_name']}"
        lines.append(f"/* ID {i + 1} - {name} */")
        lines.append(make_member_sql(user))
        lines.append("")

    # Random members
    used_rfid_tags = set(DEV_USER_RFID_TAGS)
    used_usernames = set(DEV_USER_USERNAMES)
    used_emails = set(DEV_USER_EMAILS)
    used_wa_ids = set()

    all_members = [
        generate_random_member(fake, used_rfid_tags, used_usernames, used_emails, used_wa_ids)
        for _ in range(count)
    ]
    ensure_coverage(all_members, fake)

    non_pending = [m for m in all_members if m["status"]["membership_status"] != "pending"]
    pending = [m for m in all_members if m["status"]["membership_status"] == "pending"]

    start_id = len(DEV_USERS) + 1

    # Assign IDs to non-pending first, then pending (highest IDs).
    active_ids, suspended_ids = [], []
    if non_pending:
        np_end_id = start_id + len(non_pending) - 1
        lines.append("")
        lines.append("/* =====================================================")
        lines.append(f" * Random Members (IDs {start_id}-{np_end_id})")
        lines.append(" * ===================================================== */")
        lines.append("")
        for i, member in enumerate(non_pending):
            mid = start_id + i
            st = member["status"]["membership_status"]
            if st == "active":
                active_ids.append(mid)
            elif st == "suspended":
                suspended_ids.append(mid)
            name = f"{member['identity']['first_name']} {member['identity']['last_name']}"
            lines.append(f"/* ID {mid} - {name} */")
            member.pop("_meta", None)
            lines.append(make_member_sql(member))
            lines.append("")

    if pending:
        p_start_id = start_id + len(non_pending)
        p_end_id = p_start_id + len(pending) - 1
        lines.append("")
        lines.append("/* =====================================================")
        lines.append(f" * Pending Members (IDs {p_start_id}-{p_end_id})")
        lines.append(" *")
        lines.append(" * Inserted last so they get the highest IDs and appear")
        lines.append(" * at the top of the admin portal's default member list.")
        lines.append(" * ===================================================== */")
        lines.append("")
        for i, member in enumerate(pending):
            mid = p_start_id + i
            name = f"{member['identity']['first_name']} {member['identity']['last_name']}"
            lines.append(f"/* ID {mid} - {name} */")
            member.pop("_meta", None)
            lines.append(make_member_sql(member))
            lines.append("")

    # Role assignments (dev users + random role-holders)
    extra_assignments = assign_random_roles(active_ids, suspended_ids, len(all_members))
    lines.append("")
    lines.append("/* =====================================================")
    lines.append(" * Role Assignments")
    lines.append(" * Roles: Authorizer (1), Administrator (2), Board (3), ID Check (4), CTO (5), Treasurer (6), Area Host (7)")
    lines.append(" * ===================================================== */")
    lines.append("")
    lines.append(generate_role_assignments_sql(extra_assignments))
    lines.append("")

    # Sequence reset
    lines.append("")
    lines.append("/* Reset the member identity sequence to account for seed data */")
    lines.append("SELECT setval(pg_get_serial_sequence('member', 'id'), (SELECT MAX(id) FROM member));")
    lines.append("")

    return "\n".join(lines)


### CLI

def main():
    parser = argparse.ArgumentParser(
        description="Generate seed data SQL for the Deep Harbor CRM database.",
        epilog="Example: uv run pg/tools/generate_seed_data.py --seed abc123 --count 50",
    )
    parser.add_argument(
        "--seed", type=str, default=None,
        help="Seed for reproducible output. If omitted, a random seed is generated and printed to stderr.",
    )
    parser.add_argument(
        "--count", type=int, default=15,
        help="Number of ADDITIONAL random members beyond the 11 dev users (default: 15, for 26 total).",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path. Defaults to stdout.",
    )

    args = parser.parse_args()

    seed = args.seed
    if seed is None:
        seed = secrets.token_hex(8)
        print(f"Generated seed: {seed}", file=sys.stderr)

    sql = generate_sql(args.count, seed)

    if args.output:
        with open(args.output, "w") as f:
            f.write(sql)
        print(f"Wrote {args.output} ({args.count + len(DEV_USERS)} members)", file=sys.stderr)
    else:
        print(sql)


if __name__ == "__main__":
    main()
