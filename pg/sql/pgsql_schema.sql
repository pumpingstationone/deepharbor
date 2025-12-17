CREATE ROLE root WITH LOGIN SUPERUSER PASSWORD 'rootpass';
CREATE ROLE deepharbor_owner NOLOGIN;
GRANT ALL PRIVILEGES ON DATABASE deepharbor TO deepharbor_owner;
GRANT deepharbor_owner TO dh;
/* Create a read-only user for reporting purposes */
CREATE USER dh_ro WITH PASSWORD 'dh_ro';
GRANT CONNECT ON DATABASE deepharbor TO dh_ro;
GRANT USAGE ON SCHEMA public TO dh_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dh_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO dh_ro;
/* Switch to the deepharbor database to create the schema */
\c deepharbor

/************************************************************************
 *
 * Deep Harbor PostgreSQL Database Schema
 * 
 * This file contains the SQL commands to create the database schema
 * for the Deep Harbor membership management system.
 *
 ***********************************************************************/


/* 
 * These are the two most important tables in the database - member
 * holds all the member records, and member_audit holds the audit
 * trail for changes to those records.
 */
CREATE TABLE IF NOT EXISTS member (id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY, identity JSONB NOT NULL, connections JSONB NULL, status JSONB NULL, forms JSONB, access JSONB, authorizations JSONB, extras JSONB, notes JSONB, date_added TIMESTAMP(6) WITH TIME ZONE DEFAULT now() NOT NULL, date_modified TIMESTAMP(6) WITH TIME ZONE DEFAULT now() NOT NULL);
CREATE TABLE IF NOT EXISTS member_audit (id INTEGER NOT NULL, identity JSONB NOT NULL, connections JSONB NULL, status JSONB NULL, forms JSONB, access JSONB, authorizations JSONB, extras JSONB, notes JSONB, version INTEGER NOT NULL, hash text NOT NULL, date_added TIMESTAMP(6) WITH TIME ZONE NOT NULL);
-- Foreign key constraint to link member_audit to member
ALTER TABLE member_audit ADD CONSTRAINT fk_member_audit_member_id FOREIGN KEY (id) REFERENCES member(id) ON DELETE CASCADE;


COMMENT ON TABLE member IS 'This table holds the member records for all Deep Harbor members.';
COMMENT ON TABLE member_audit IS 'This table holds the audit trail for changes to member records. Each time a member record is inserted or updated, a new record is created here with a version.';

/* 
 * Indexes to optimize queries on member and member_audit tables
 */
-- Indexes for member table
CREATE INDEX IF NOT EXISTS idx_member_id ON member (id);
CREATE INDEX IF NOT EXISTS idx_member_date_added ON member (date_added);
CREATE INDEX IF NOT EXISTS idx_member_date_modified ON member (date_modified);
CREATE INDEX IF NOT EXISTS idx_member_identity ON member USING GIN (identity);
CREATE INDEX IF NOT EXISTS idx_member_status ON member USING GIN (status); 
CREATE INDEX IF NOT EXISTS idx_member_access ON member USING GIN (access);
CREATE INDEX IF NOT EXISTS idx_member_access_rfid_tags_gin ON member USING GIN ((access->'rfid_tags'));
CREATE INDEX IF NOT EXISTS idx_member_authorizations ON member USING GIN (authorizations);

-- Indexes for member_audit table
CREATE INDEX IF NOT EXISTS idx_member_audit_id ON member_audit (id);
CREATE INDEX IF NOT EXISTS idx_member_audit_id_version ON member_audit (id, version);
CREATE INDEX IF NOT EXISTS idx_member_audit_date_added ON member_audit (date_added);
CREATE INDEX IF NOT EXISTS idx_member_audit_identity ON member_audit USING GIN (identity);
CREATE INDEX IF NOT EXISTS idx_member_audit_status ON member_audit USING GIN (status); 
CREATE INDEX IF NOT EXISTS idx_member_audit_access ON member_audit USING GIN (access);
CREATE INDEX IF NOT EXISTS idx_member_audit_access_rfid_tags_gin ON member_audit USING GIN ((access->'rfid_tags'));
CREATE INDEX IF NOT EXISTS idx_member_audit_authorizations ON member_audit USING GIN (authorizations);

/*
 * Member views - these views provide summary information about members
 * and are meant to be shortcuts when running reports or queries so
 * you don't have to write the same SQL over and over again.
 */

-- Status counts view 
CREATE VIEW v_member_status_counts AS
SELECT 'ACTIVE' AS status, 
       COUNT(*) 
FROM   member 
WHERE  UPPER((status->>'membership_status')::TEXT) = 'ACTIVE' 

UNION ALL

SELECT 'INACTIVE' AS status, 
       COUNT(*) 
FROM   member 
WHERE  UPPER((status->>'membership_status')::TEXT) != 'ACTIVE';
COMMENT ON VIEW v_member_status_counts IS 'This view shows the count of active and inactive members based on the membership_status field in the status JSONB column of the member table.';

-- Member names and status view
CREATE VIEW v_member_names_and_status AS
SELECT id, 
       identity->>'first_name' AS first_name, 
       identity->>'last_name' AS last_name,
       status->>'membership_status' AS membership_status
FROM   member;
COMMENT ON VIEW v_member_names_and_status IS 'This view provides a list of member IDs along with their first name, last name, and membership status from the member table.';

/* 
 * OAuth2 Clients table - this holds the client credentials
 * for any OAuth2 clients that need to access the API.
 */
CREATE TABLE 
    oauth2_users 
    ( 
                client_name        TEXT NOT NULL, 
                client_secret      TEXT NOT NULL, 
                date_added         TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
                client_description TEXT, 
                PRIMARY KEY (client_name) 
    );
/* Our initial OAuth2 client for dev web services */
INSERT INTO oauth2_users (client_name, client_secret, date_added, client_description) VALUES ('dev-dhservices-v1', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', '2025-01-20 14:54:39', 'dev web services v1');

COMMENT ON TABLE oauth2_users IS 'This table holds the OAuth2 client credentials for applications that need to access the Deep Harbor API.';

/* 
 * For Wild Apricot sync tracking - this can go away once
 * we're no longer using Wild Apricot 
 */
CREATE TABLE wild_apricot_sync 
(
    id INTEGER PRIMARY KEY DEFAULT 1,
    last_sync_timestamp TIMESTAMP NOT NULL,
    CONSTRAINT single_row_check CHECK (id = 1)
);
COMMENT ON TABLE wild_apricot_sync IS 'This table tracks the last synchronization timestamp with Wild Apricot. It contains a single row with id=1.';

/* 
 * Functions for Wiegand conversion - this is used for the RFID
 * tags PS1 uses
 */

CREATE FUNCTION convertfromwiegand (p_num integer)  RETURNS integer
  VOLATILE
AS $body$
DECLARE
    v_baseVal varchar(8);
    v_facilityCode varchar(3);
    v_userCode varchar(5);

    v_bitCountdown integer := 24;

    -- All the facility variables we use
    v_facilityBits varchar(8);
    v_fbVal varchar(1);
    v_facilityBitTable varchar array[8]; 
    v_fcPos integer := 1;
    v_facilitySum integer := 0;

    -- And all the user variables
    v_userBits varchar(255);
    v_ubVal varchar(1);
    v_userBitTable varchar array[16];
    v_ucPos integer := 1;
    v_userSum integer := 0;

BEGIN
    v_baseVal := p_num::VARCHAR(8);

    -- We have to be careful about the facility code because it could be 
    -- three digits or less, while the user code will always be five
    -- digits
    v_facilityCode := substring(v_baseVal from 1 for length(v_baseVal) - 5);
    v_userCode := SUBSTRING(v_baseVal from length(v_baseVal) - 4);
    --raise notice '[%] - [%]', v_facilityCode, v_userCode;

    -- Okay, here we go with all our bit-twiddling logic....

    ----------------------------------------------------------------------
    -- Facility Code Logic
    ----------------------------------------------------------------------
    v_facilityBits := v_facilityCode::Integer::bit(8)::varchar;

    for pos in 1..8 loop
        v_fbVal := substring(v_facilityBits from pos for 1);
        if v_fbVal = '1' THEN
            v_facilityBitTable[v_fcPos] = pow(2, v_bitCountdown - 1)::integer::varchar;
        ELSE
            v_facilityBitTable[v_fcPos] = '0';
        end if;

        v_fcPos := v_fcPos + 1;
        v_bitCountdown := v_bitCountdown - 1;
    end loop; 

    for var in array_lower(v_facilityBitTable, 1)..array_upper(v_facilityBitTable, 1) loop
        --raise notice '--> [%]', v_facilityBitTable[var];
        v_facilitySum := v_facilitySum + v_facilityBitTable[var]::INTEGER;
    end loop;

    ----------------------------------------------------------------------
    -- User Code Logic
    ----------------------------------------------------------------------
    v_userBits := v_userCode::INTEGER::bit(16)::VARCHAR;

    for pos in 1..16 loop
        v_ubVal := substring(v_userBits from pos for 1);
        if v_ubVal = '1' THEN
            v_userBitTable[v_ucPos] = pow(2, v_bitCountdown - 1)::integer::varchar;
        ELSE
            v_userBitTable[v_ucPos] = '0';
        end if;

        v_ucPos := v_ucPos + 1;
        v_bitCountdown := v_bitCountdown - 1;
    end loop; 

    for var in array_lower(v_userBitTable, 1)..array_upper(v_userBitTable, 1) loop
        --raise notice '--> [%]', v_userBitTable[var];
        v_userSum := v_userSum + v_userBitTable[var]::INTEGER;
    end loop;

    return (select v_facilitySum + v_userSum);
end;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION convertfromwiegand(integer) IS 'Converts a Wiegand 24-bit integer value into the corresponding facility code and user code integer value.';

CREATE FUNCTION converttowiegand (p_num integer)  RETURNS integer
  VOLATILE
AS $body$
DECLARE
    v_baseVal VARCHAR(24) := '';
    v_fc VARCHAR(8) := '';
    v_uc VARCHAR(16) := '';

    v_fNum INTEGER;
    v_uNum INTEGER;

    v_FinalNum varchar(16) := '';
BEGIN
    -- Convert the number passed to us as a binary string
    v_baseVal := CAST(p_num::bit(24)::VARCHAR AS VARCHAR(24));
    -- Okay, we need two parts, the facility code, and the user code
    v_fc := SUBSTRING(v_baseVal from 1 for 8);
    v_uc := SUBSTRING(v_baseVal from 9);
    
    -- Now we're going to convert the bits to numbers
    v_fNum := (v_fc::bit(8))::integer;
    v_uNum := (v_uc::bit(16))::integer;
  
    -- And put it all together    
    v_FinalNum := format('%s%s', v_fNum::varchar, v_uNum::varchar);
  
    RETURN (SELECT v_FinalNum::integer);
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION converttowiegand(integer) IS 'Converts a facility code and user code integer value into the corresponding Wiegand 24-bit integer value.';

CREATE FUNCTION get_all_tags_for_member(IN p_member_id INTEGER)
RETURNS TABLE(tag TEXT, wiegand_tag_num INTEGER, status TEXT)
AS $body$
BEGIN
        /* 
         * This function retrieves all RFID tags associated with a member,
         * both from the current member record and from the member_audit
         * table, indicating whether each tag is currently active or inactive.
         */
        RETURN QUERY 
        WITH all_tags AS
             (       SELECT DISTINCT jsonb_array_elements_text(COALESCE(ma.access-> 'rfid_tags', '[]'::jsonb)) AS tag
                     FROM    member_audit ma
                     WHERE   ma.id = p_member_id
                     
                     UNION
                     
                     SELECT DISTINCT jsonb_array_elements_text(COALESCE(m.access-> 'rfid_tags', '[]'::jsonb)) AS tag
                     FROM   member m
                     WHERE  m.id = p_member_id
             )
        SELECT   at.tag,
                 converttowiegand(at.tag::INTEGER) WIEGAND_TAG_NUM,
                 CASE
                          WHEN EXISTS (    SELECT 1
                                           FROM    member m
                                           WHERE   m.id = p_member_id
                                           AND     m.access->'rfid_tags' @> ('["' || at.tag || '"]')::jsonb )
                          THEN 'ACTIVE'
                          ELSE 'INACTIVE'
                 END AS status
        FROM     all_tags at
        ORDER BY at.tag;
END;
$body$
LANGUAGE plpgsql;
COMMENT ON FUNCTION get_all_tags_for_member(INTEGER) IS 'This function retrieves all RFID tags associated with a member from both the member and member_audit tables, indicating whether each tag is currently active or inactive.';

/* 
 * member Audit Trigger and Functions
 * This trigger will create an audit record in the member_audit table
 * whenever a member record is inserted or updated which is how we
 * maintain a history of changes to member records over time.
 */

CREATE FUNCTION add_member_audit_record ()  RETURNS trigger
  VOLATILE
AS $body$
DECLARE
    new_hash text;
BEGIN
    -- We want to hash the new record to create a unique fingerprint
    -- for this version of the member record, as well as the previous
    -- record if it exists.
    new_hash := '';

    -- Compute the hash of the new record combined with the previous record
    SELECT 
        encode(sha256(convert_to(
            (COALESCE(
                (SELECT row_to_json(old_record) FROM member_audit old_record WHERE old_record.id = new.id ORDER BY old_record.version DESC LIMIT 1)::TEXT,
                ''
            ) || 
            row_to_json(new)::TEXT
        ), 'UTF8')), 'hex')
    INTO
        new_hash;

    -- Now insert the changes, along with the new version number and hash
    INSERT INTO 
        member_audit 
        ( 
            id, 
            identity, 
            connections, 
            status, 
            forms, 
            ACCESS, 
            authorizations, 
            extras, 
            notes,
            HASH,
            VERSION,
            date_added 
        )
        VALUES 
        ( 
            new.id, 
            new.identity, 
            new.connections, 
            new.status, 
            new.forms, 
            new.access, 
            new.authorizations, 
            new.extras, 
            new.notes,
            new_hash,
            COALESCE (1 + 
            (   SELECT 
                    max(VERSION)
                FROM 
                    member_audit 
                WHERE 
                    id = new.id), 1), 
            CURRENT_TIMESTAMP 
        );
RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION add_member_audit_record() IS 'This function adds an audit record to the member_audit table whenever a member record is inserted or updated. It increments the version number for each change.';

CREATE TRIGGER trigger_update_member_audit
  AFTER INSERT OR UPDATE ON member
  FOR EACH ROW
EXECUTE FUNCTION add_member_audit_record();
COMMENT ON TRIGGER trigger_update_member_audit ON member IS 'This trigger calls the add_member_audit_record function after each insert or update on the member table to maintain an audit trail of changes.';
/*
 * member date_modified Trigger and Function
 * This trigger will update the date_modified column to the current
 * timestamp whenever a member record is updated.
 */
CREATE OR REPLACE FUNCTION update_date_modified_column() RETURNS trigger
VOLATILE 
AS $body$
BEGIN
    NEW.date_modified = NOW();
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION update_date_modified_column() IS 'This function updates the date_modified column to the current timestamp before an update operation on the member table.';

CREATE TRIGGER trigger_update_member_date_modified
BEFORE UPDATE ON member
FOR EACH ROW
EXECUTE PROCEDURE update_date_modified_column();
COMMENT ON TRIGGER trigger_update_member_date_modified ON member IS 'This trigger calls the update_date_modified_column function before each update on the member table to set the date_modified column to the current timestamp.';

/*
 * member Changes Table and Trigger for DHDispatcher
 */

-- This is the job table that will be populated by column triggers on the
-- member table. The DHDispatcher program listens on this table for
-- unprocessed records ('processed' field is set to false) and hands off
-- the changes to downstream systems for whatever they're supposed to do
-- with the new information.
CREATE TABLE IF NOT EXISTS member_changes (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  member_id INTEGER,
  data JSONB,
  date_added TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
  processed BOOLEAN NOT NULL DEFAULT FALSE,
  CONSTRAINT fk_member_changes_member_id FOREIGN KEY (member_id) REFERENCES member(id) ON DELETE CASCADE
);
COMMENT ON TABLE member_changes IS 'This table logs changes to member records for processing by DHDispatcher. Each record includes the member_id, change data in JSONB format, a timestamp, and a processed flag.';

-- This table logs the results of processing attempts by DHDispatcher
-- for each member_changes record. If there is an error during processing,
-- the error message and other details are logged here for DH administrators
-- to review.
CREATE TABLE IF NOT EXISTS member_changes_processing_log (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  member_change_id INTEGER,
  service_name TEXT,
  service_endpoint TEXT,
  response_code INTEGER,
  response_message TEXT,
  date_updated TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_member_changes_processing_log_member_change_id FOREIGN KEY (member_change_id) REFERENCES member_changes(id) ON DELETE CASCADE
);
COMMENT ON TABLE member_changes_processing_log IS 'This table logs the results of processing attempts by DHDispatcher for each member_changes record, including service name, endpoint, response code, and message.';

/* View to show processed vs unprocessed member changes */
CREATE VIEW v_member_change_status AS
SELECT 'processed' AS status, 
       COUNT(*) 
FROM   member_changes 
WHERE  processed = true
 
UNION ALL
 
SELECT 'unprocessed' AS status, 
       COUNT(*) 
FROM   member_changes 
WHERE  processed = false;
COMMENT ON VIEW v_member_change_status IS 'This view shows the count of processed and unprocessed member changes in the member_changes table.';

-- Index to optimize queries for unprocessed member changes
CREATE INDEX IF NOT EXISTS idx_member_changes_unprocessed 
  ON member_changes (id) 
  WHERE processed = FALSE;
COMMENT ON INDEX idx_member_changes_unprocessed IS 'This index optimizes queries for unprocessed member changes in the member_changes table.';

CREATE OR REPLACE FUNCTION notify_member_changes_insert_id() RETURNS trigger 
AS $body$
BEGIN
  -- Send only the new row id (as text) on channel "member_changes_insert". 
  PERFORM pg_notify('member_changes_insert', NEW.id::text);
  RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION notify_member_changes_insert_id() IS 'This function sends a notification on the member_changes_insert channel with the new member_changes row id after an insert operation.';

CREATE TRIGGER trigger_insert_member_changes
  AFTER INSERT ON member_changes
  FOR EACH ROW
  EXECUTE PROCEDURE notify_member_changes_insert_id();
COMMENT ON TRIGGER trigger_insert_member_changes ON member_changes IS 'This trigger calls the notify_member_changes_insert_id function after each insert on the member_changes table to notify listeners (e.g., DHDispatcher) of new changes.';

/*
 * Triggers to log changes to specific columns in the member table
 * into the member_changes table for processing by DHDispatcher.
 */

-- This function will be called by triggers on the member table
-- to log changes to specific columns into the member_changes table.
-- It handles both INSERT and UPDATE operations.
CREATE OR REPLACE FUNCTION log_member_changes()
RETURNS TRIGGER AS $body$
DECLARE
    change_data JSONB;
BEGIN
    -- Initialize with the member_id
    change_data := jsonb_build_object('member_id', NEW.id);
    
    -- Check each monitored column and add to change_data if changed
    -- For INSERT, OLD is NULL so we check TG_OP
    
    IF TG_OP = 'INSERT' THEN
        IF NEW.identity IS NOT NULL THEN
            change_data := change_data || jsonb_build_object('change', 'identity', 'identity', NEW.identity);
        END IF;
        IF NEW.status IS NOT NULL THEN
            change_data := change_data || jsonb_build_object('change', 'status', 'status', NEW.status);
        END IF;
        IF NEW.access IS NOT NULL THEN
            change_data := change_data || jsonb_build_object('change', 'access', 'access', NEW.access);
        END IF;
        IF NEW.authorizations IS NOT NULL THEN
            change_data := change_data || jsonb_build_object('change', 'authorizations', 'authorizations', NEW.authorizations);
        END IF;
    ELSE
        -- UPDATE operation - only log changed columns
        IF NEW.identity IS DISTINCT FROM OLD.identity THEN
            change_data := change_data || jsonb_build_object('change', 'identity', 'identity', NEW.identity);
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            change_data := change_data || jsonb_build_object('change', 'status', 'status', NEW.status);
        END IF;
        IF NEW.access IS DISTINCT FROM OLD.access THEN
            change_data := change_data || jsonb_build_object('change', 'access', 'access', NEW.access);
        END IF;
        IF NEW.authorizations IS DISTINCT FROM OLD.authorizations THEN
            change_data := change_data || jsonb_build_object('change', 'authorizations', 'authorizations', NEW.authorizations);
        END IF;
    END IF;
    
    -- Only insert if there are actual changes (more than just member_id)
    IF change_data != jsonb_build_object('member_id', NEW.id) THEN
        INSERT INTO member_changes (member_id, data)
        VALUES (NEW.id, change_data);
    END IF;
    
    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION log_member_changes() IS 'This function logs changes to specific columns (status, access, authorizations) in the member table into the member_changes table for processing by DHDispatcher. It handles both INSERT and UPDATE operations.';

-- Create the trigger for INSERT operations on the monitored columns
-- of the member table.
CREATE OR REPLACE TRIGGER trigger_member_changes_insert
    AFTER INSERT ON member
    FOR EACH ROW
    WHEN (NEW.status IS NOT NULL 
          OR NEW.access IS NOT NULL 
          OR NEW.authorizations IS NOT NULL
          OR NEW.identity IS NOT NULL)
    EXECUTE FUNCTION log_member_changes();
COMMENT ON TRIGGER trigger_member_changes_insert ON member IS 'This trigger calls the log_member_changes function after each insert on the member table to log changes to monitored columns into the member_changes table.';

-- Create the trigger for UPDATE operations on the monitored columns
-- of the member table.
CREATE OR REPLACE TRIGGER trigger_member_changes_update
    AFTER UPDATE ON member
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status
          OR OLD.access IS DISTINCT FROM NEW.access
          OR OLD.authorizations IS DISTINCT FROM NEW.authorizations
          OR OLD.identity IS DISTINCT FROM NEW.identity)
    EXECUTE FUNCTION log_member_changes();
COMMENT ON TRIGGER trigger_member_changes_update ON member IS 'This trigger calls the log_member_changes function after each update on the member table to log changes to monitored columns into the member_changes table.';

-- View to show unprocessed member changes with member full name
-- for easier identification by the DH administrators when reviewing
-- unprocessed changes.
CREATE VIEW v_unprocessed_member_changes AS
SELECT     m.id member_id,
           (m.identity->>'first_name')::TEXT || ' ' || (m.identity->>'last_name')::TEXT AS member_full_name,
           mc.data change,
           mc.date_added change_added_timestamp
FROM       member m
INNER JOIN member_changes mc ON m.id = mc.member_id
WHERE      mc.processed = false
ORDER BY   mc.date_added;
COMMENT ON VIEW v_unprocessed_member_changes IS 'This view shows unprocessed member changes along with the full name of the member for easier identification by DH administrators.';


/*
 * Endpoints table- this is used to track what the endpoints are
 * that DHDispatcher should send data to.
 */
CREATE TABLE service_endpoints 
( 
    NAME       TEXT NOT NULL, 
    endpoint   TEXT NOT NULL, 
    PRIMARY KEY (NAME) 
);
COMMENT ON TABLE service_endpoints IS 'This table holds the service endpoints that DHDispatcher will send member changes to.';

/* Our initial endpoints for the V1 version */
INSERT INTO service_endpoints (name, endpoint) VALUES 
('status', 'http://dhstatus:8000/v1/change_status'),
('access', 'http://dhaccess:8000/v1/change_access'),
('events', 'http://dhevents:8000/v1/change_events'),
('authorizations', 'http://dhauthorizations:8000/v1/change_authorizations'),
('identity', 'http://dhidentity:8000/v1/change_identity');

/*
 * Member passwords
 * Here we defined all the stuff we need to store and manage passwords
 * for members. These are hashed passwords only, never plaintext.
 * The member interacts with the system to set or change their password,
 * via the website or API, and we store only the hash here.
 */

-- Table to store password hashes for members.
-- member_id references member(id) and is the primary key so there's at most one password row per member.
CREATE TABLE IF NOT EXISTS member_password (
  member_id integer PRIMARY KEY REFERENCES member(id) ON DELETE CASCADE,
  password_hash text NOT NULL,
  date_added timestamptz NOT NULL DEFAULT now(),
  date_modified timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE member_password IS 'This table stores hashed passwords for members. Each member can have at most one password entry.';

-- Upsert function: hash the supplied plaintext password and insert or update the row.
CREATE OR REPLACE FUNCTION upsert_member_password(p_member_id integer, p_password text)
RETURNS void
LANGUAGE plpgsql
AS $body$
DECLARE
  v_hash text;
BEGIN
  IF p_member_id IS NULL OR p_password IS NULL OR length(p_password) = 0 THEN
    RAISE EXCEPTION 'member_id and password must be provided and password must be non-empty';
  END IF;

  v_hash := crypt(p_password, gen_salt('bf', 12));

  INSERT INTO member_password (member_id, password_hash)
  VALUES (p_member_id, v_hash)
  ON CONFLICT (member_id) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        date_modified = now();
END;
$body$;
COMMENT ON FUNCTION upsert_member_password(integer, text) IS 'This function hashes the supplied plaintext password and inserts or updates the member_password table for the given member_id.';

-- debugging - verify a plaintext password against the stored hash.
CREATE OR REPLACE FUNCTION verify_member_password(p_member_id integer, p_password text)
RETURNS boolean
LANGUAGE plpgsql
AS $body$
DECLARE
  v_hash text;
BEGIN
  IF p_member_id IS NULL OR p_password IS NULL THEN
    RETURN false;
  END IF;

  SELECT password_hash INTO v_hash
  FROM member_password
  WHERE member_id = p_member_id;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  -- crypt(pw, stored_hash) returns the hash computed with the salt from stored_hash;
  -- comparing equality is the correct verification pattern.
  RETURN v_hash = crypt(p_password, v_hash);
END;
$body$;
COMMENT ON FUNCTION verify_member_password(integer, text) IS 'This function verifies a plaintext password against the stored hash for the given member_id and returns true if they match, false otherwise.';

/*
 * Lookup tables
 * These tables hold various lookup values used in the system.
 */
CREATE TABLE IF NOT EXISTS membership_types_lookup (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT);
COMMENT ON TABLE membership_types_lookup IS 'This table holds the membership types used in the Deep Harbor system.';

/* Hard-coded membership types from Wild Apricot */
insert into membership_types_lookup (id, name) values
        (1, 'Area Host'),
        (2, 'Board Member / Officer'),
        (3, 'Contractor'),
        (4, 'Member - Cash Payment'),
        (5, 'Member - Grandfathered Price'),
        (6, 'Member - PayPal'),
        (7, 'Member w/ Storage - Cash Payment'),
        (8, 'Member w/ Storage - Grandfathered Price'),
        (9, 'Member w/ Storage - PayPal'),
        (10, 'New Member'),
        (11, 'Scholarship'),
        (12, 'Stripe Member - $65'),
        (13, 'Stripe Member w/ Storage - $95'),
        (14, 'Stripe Volunteer w/ Paid Storage - $30'),
        (15, 'Volunteer'),
        (16, 'Volunteer w/ Free Storage'),
        (17, 'Volunteer w/ Paid Storage');

CREATE TABLE IF NOT EXISTS authorization_types_lookup (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT);
COMMENT ON TABLE authorization_types_lookup IS 'This table holds the authorization types (i.e. the various equipment authorizations) used in the Deep Harbor system.';

-- Hard-coded authorization types specific to the PS1 hackspace
-- as of December 2025
insert into authorization_types_lookup (id, name) values
        (1, 'Boss Authorized Users'),
        (2, 'CNC Plasma Authorized Users'),
        (3, 'Epilog Authorized Users'),
        (4, 'ShopBot Authorized Users'),
        (5, 'Tormach Authorized Users'),
        (6, 'Universal Authorized Users'),
        (7, 'Vinyl Cutter Authorized Users'),
        (8, 'Mimaki CJV30 printer Users'),
        (9, 'Band Saw'),
        (10, 'Billiards'),
        (11, 'Blacksmithing'),
        (12, 'Bridgeport Mill'),
        (13, 'Button sewing machines'),
        (14, 'Clausing Lathe'),
        (15, 'Coffee Roaster'),
        (16, 'Cold Metals Basic'),
        (17, 'Drum Sander'),
        (18, 'Ender 3D Printers'),
        (19, 'Formlabs Form 3 printer'),
        (20, 'Hand held plasma cutter'),
        (21, 'Jointer'),
        (22, 'LeBlond Lathe'),
        (23, 'Metal Band Saw'),
        (24, 'Metal Drill Press'),
        (25, 'Mig Welders'),
        (26, 'Mitre Saw'),
        (27, 'Multi-Router'),
        (28, 'Panel Saw'),
        (29, 'Planer'),
        (30, 'Pneumatic Power Tools'),
        (31, 'Powder Coating Equipment'),
        (32, 'Prusa 3D printers'),
        (33, 'Router Table'),
        (34, 'Sanders'),
        (35, 'Saw Dado'),
        (36, 'Serger sewing machine'),
        (37, 'Square Chisel Morticer'),
        (38, 'Surface Grinder'),
        (39, 'Table Saw'),
        (40, 'Tier one Sewing Machine'),
        (41, 'Tig Welders'),
        (42, 'Tube Bending Equipment'),
        (43, 'Wood Drill Press'),
        (44, 'Wood Lathe'),
        (45, 'Wood Mini Lathe');

/*
 * Activity tables
 */

-- This table logs member access of the doors using RFID tags.
CREATE TABLE IF NOT EXISTS member_access_logs (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  member_id INTEGER REFERENCES member(id) ON DELETE SET NULL,
  rfid_tag TEXT NOT NULL,
  access_point TEXT NOT NULL,
  access_granted BOOLEAN NOT NULL,
  timestamp TIMESTAMP(6) WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);
COMMENT ON TABLE member_access_logs IS 'This table logs member access events (i.e. front door, back door) using RFID tags';