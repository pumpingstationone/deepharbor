-- =============================================================================
-- Equipment Module — Production Seed Data Template
-- Runs automatically on first `docker compose up` (idempotent).
--
-- HOW TO USE THIS FILE:
--   1. Replace the placeholder values below with your real data.
--   2. Add or remove rows as needed — the structure repeats.
--   3. Commit the updated file before spinning up production.
--
-- All inserts are ON CONFLICT DO NOTHING, so re-running is safe.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- AREAS
-- Columns: name (unique), description, metadata (JSONB — optional extra fields)
--
-- metadata examples:
--   '{"contact_name":"Shop Lead","host_discord":"shop-leads-channel"}'
--   '{"host_email":"shop@example.com","website":"https://example.com"}'
-- -----------------------------------------------------------------------------
INSERT INTO areas (name, description, metadata) VALUES
  -- ('Area Name',  'Brief description of the area.',  '{"contact_name":"Name","host_discord":"channel-name"}'),
  -- ('Area Name 2','Another area description.',        '{}'),
  ('REPLACE ME', 'Replace with real area name and description.', '{}')
ON CONFLICT (name) DO NOTHING;


-- -----------------------------------------------------------------------------
-- EQUIPMENT  +  EQUIPMENT GROUPS
-- Wrapped in a DO block so we can resolve area IDs by name.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
  -- Declare one variable per area (add/remove to match your areas above)
  -- a_<shortname>  INTEGER;
  a_area1  INTEGER;

  -- Declare one variable per equipment group
  -- g_<groupname>  INTEGER;
  g_group1 INTEGER;

  -- Declare one variable per piece of equipment (needed for group membership)
  -- e_<shortname>  INTEGER;
  e_equip1 INTEGER;

BEGIN
  -- -------------------------------------------------------------------------
  -- Resolve area IDs from the names you inserted above
  -- -------------------------------------------------------------------------
  -- SELECT id INTO a_<shortname> FROM areas WHERE name = 'Area Name';
  SELECT id INTO a_area1 FROM areas WHERE name = 'REPLACE ME';


  -- -------------------------------------------------------------------------
  -- EQUIPMENT
  -- Required: make, model, serial_number (must be unique across all equipment)
  -- Optional but recommended: common_name, area_id, build_date, schedulable,
  --                            electrical (JSONB), breaker (JSONB), attributes (JSONB)
  --
  -- electrical example:
  --   '{"voltage":240,"amperage":30,"phase":"single","plug_type":"NEMA 6-30P","notes":"Dedicated circuit"}'
  --   phase values: "single" | "three"
  --
  -- breaker example:
  --   '{"panel":"A","breaker_number":12,"location_description":"West wall panel","notes":""}'
  --
  -- attributes: any free-form key/value pairs relevant to the equipment type
  --   '{"blade_size_in":10,"riving_knife":true}'
  --   '{"build_volume_mm":"256x256x256","max_speed_mm_s":500}'
  --
  -- status values: 'active' | 'inactive' | 'under_repair' | 'decommissioned'
  -- schedulable: TRUE if members can book time on this equipment
  -- -------------------------------------------------------------------------

  -- Template row — duplicate this block for each piece of equipment:
  INSERT INTO equipment (area_id, common_name, make, model, serial_number, build_date, status, schedulable, electrical, breaker, attributes)
  VALUES
    -- (
    --   a_area1,                 -- area variable declared above, or NULL
    --   'Common Name',           -- human-friendly label shown in UI
    --   'Manufacturer',          -- make  (required)
    --   'Model Number',          -- model (required)
    --   'UNIQUE-SERIAL-001',     -- serial_number (required, must be globally unique)
    --   '2020-01-01',            -- build_date (YYYY-MM-DD) or NULL
    --   'active',                -- status
    --   FALSE,                   -- schedulable
    --   '{"voltage":120,"amperage":15,"phase":"single","plug_type":"NEMA 5-15P"}',
    --   '{"panel":"A","breaker_number":1}',
    --   '{}'                     -- extra attributes
    -- ),
    (
      NULL,                    -- replace NULL with e.g. a_area1
      'REPLACE ME',
      'REPLACE MAKE',
      'REPLACE MODEL',
      'REPLACE-SERIAL-001',
      NULL,
      'active',
      FALSE,
      '{}',
      '{}',
      '{}'
    )
  ON CONFLICT (serial_number) DO NOTHING;


  -- -------------------------------------------------------------------------
  -- EQUIPMENT GROUPS
  -- Groups let you organize related equipment together (e.g. "CNC Machines").
  -- Each group has a name, optional description, and optional home area.
  -- -------------------------------------------------------------------------

  -- Template — duplicate for each group:
  INSERT INTO equipment_groups (name, description, area_id)
  SELECT
    'REPLACE GROUP NAME',
    'Replace with a description of what this group contains.',
    NULL   -- or: (SELECT id FROM areas WHERE name = 'Area Name')
  ON CONFLICT DO NOTHING;

  -- Resolve group IDs
  -- SELECT id INTO g_<groupname> FROM equipment_groups WHERE name = 'Group Name';
  SELECT id INTO g_group1 FROM equipment_groups WHERE name = 'REPLACE GROUP NAME';


  -- -------------------------------------------------------------------------
  -- EQUIPMENT → GROUP MEMBERSHIP
  -- After inserting equipment and groups, resolve equipment IDs and link them.
  -- -------------------------------------------------------------------------

  -- Resolve equipment IDs by serial number:
  -- SELECT id INTO e_<shortname> FROM equipment WHERE serial_number = 'UNIQUE-SERIAL-001';
  SELECT id INTO e_equip1 FROM equipment WHERE serial_number = 'REPLACE-SERIAL-001';

  -- Insert memberships (sort_order controls display order within the group):
  INSERT INTO equipment_group_members (group_id, equipment_id, sort_order) VALUES
    -- (g_group1, e_equip1, 1),
    -- (g_group1, e_equip2, 2),
    (g_group1, e_equip1, 1)
  ON CONFLICT DO NOTHING;

END $$;
