/************************************************************************
 *
 * Equipment Module Migration
 * 
 * Run this against an existing Deep Harbor database to add equipment
 * permissions to the Administrator and SuperAdmin roles.
 *
 * Safe to run multiple times — permissions are appended only if the
 * role exists and the update is idempotent (duplicate array values
 * are harmless in JSONB arrays).
 *
 * Usage:
 *   psql -U dh -d deepharbor -f pg/sql/migrate_equipment.sql
 *
 * Or via Docker:
 *   cat pg/sql/migrate_equipment.sql | docker exec -i dh_db psql -U dh deepharbor
 *
 ***********************************************************************/

BEGIN;

-- Add equipment permissions to Administrator (id=2)
UPDATE roles SET permission = jsonb_set(
    jsonb_set(permission, '{view}',
        permission->'view' || '[
            "equipment.areas",
            "equipment.items",
            "equipment.groups",
            "equipment.tickets",
            "equipment.schedules",
            "equipment.auth_sessions",
            "equipment.maintenance",
            "equipment.dashboard",
            "equipment.config"
        ]'::jsonb
    ), '{change}',
    permission->'change' || '[
        "equipment.areas",
        "equipment.items",
        "equipment.groups",
        "equipment.tickets",
        "equipment.schedules",
        "equipment.auth_sessions",
        "equipment.maintenance",
        "equipment.config"
    ]'::jsonb
) WHERE id = 2;

-- Add equipment permissions to SuperAdmin (id=5)
UPDATE roles SET permission = jsonb_set(
    jsonb_set(permission, '{view}',
        permission->'view' || '[
            "equipment.areas",
            "equipment.items",
            "equipment.groups",
            "equipment.tickets",
            "equipment.schedules",
            "equipment.auth_sessions",
            "equipment.maintenance",
            "equipment.dashboard",
            "equipment.config"
        ]'::jsonb
    ), '{change}',
    permission->'change' || '[
        "equipment.areas",
        "equipment.items",
        "equipment.groups",
        "equipment.tickets",
        "equipment.schedules",
        "equipment.auth_sessions",
        "equipment.maintenance",
        "equipment.config"
    ]'::jsonb
) WHERE id = 5;

COMMIT;
