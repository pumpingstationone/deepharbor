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
CREATE TABLE IF NOT EXISTS member (id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY, identity JSONB NOT NULL, connections JSONB NULL, status JSONB NULL, forms JSONB, access JSONB, authorizations JSONB, extras JSONB, notes JSONB, date_added TIMESTAMP(6) WITH TIME ZONE DEFAULT now() NOT NULL, date_modified TIMESTAMP(6) WITH TIME ZONE DEFAULT now() NOT NULL, last_updated_by INTEGER NULL);
CREATE TABLE IF NOT EXISTS member_audit (id INTEGER NOT NULL, identity JSONB NOT NULL, connections JSONB NULL, status JSONB NULL, forms JSONB, access JSONB, authorizations JSONB, extras JSONB, notes JSONB, version INTEGER NOT NULL, hash text NOT NULL, date_added TIMESTAMP(6) WITH TIME ZONE NOT NULL, last_updated_by INTEGER NULL, PRIMARY KEY (id, version));
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

-- Full text search index on member table (all columns except id, status, forms, date_added, date_modified)
CREATE INDEX IF NOT EXISTS idx_member_fulltext_search ON member USING GIN (
    (
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', identity, '["all"]')::text, '')) ||
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', connections, '["all"]')::text, '')) ||
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', access, '["all"]')::text, '')) ||
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', authorizations, '["all"]')::text, '')) ||
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', extras, '["all"]')::text, '')) ||
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', notes, '["all"]')::text, ''))
    )
);

-- Search index just for the identity column
CREATE INDEX IF NOT EXISTS idx_member_identity_fulltext_search ON member USING GIN (
    to_tsvector('english', COALESCE(jsonb_to_tsvector('english', identity, '["all"]')::text, ''))
);


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

-- This view wraps most of the member data for easier querying
-- and displaying on the member portal
CREATE OR REPLACE VIEW v_member_info as
SELECT m.id member_id, 
json_build_object(
    'identity', json_build_object(
        'member_id', m.id,
        'first_name', m.identity ->> 'first_name'::TEXT,
        'last_name', m.identity ->> 'last_name'::TEXT,
        'primary_email', ((m.identity -> 'emails'::TEXT) -> 0) ->> 'email_address'::TEXT,
        'nickname', m.identity ->> 'nickname'::TEXT,
        'active_directory_username', m.identity ->> 'active_directory_username'::TEXT
    ),
    'connections', json_build_object(
      'discord_username', m.connections ->> 'discord_username'::TEXT
    ),
    'forms', json_build_object(
        'id_check_1', m.forms ->> 'id_check_1'::TEXT,
        'id_check_2', m.forms ->> 'id_check_2'::TEXT,
        'waiver_signed_date', to_date(m.forms ->> 'waiver_signed_date'::TEXT, 'YYYY-MM-DD' ),
        'terms_of_use_accepted', m.forms ->> 'terms_of_use_accepted'::TEXT,
        'essentials_form', m.forms ->> 'essentials_form'::TEXT,
        'orientation_completed_date', to_date(m.forms ->> 'orientation_completed_date'::TEXT, 'YYYY-MM-DD' )
    ),
    'status', json_build_object(
        'member_since', to_date(m.status ->> 'member_since'::TEXT, 'YYYY-MM-DD'), 
        'membership_status', m.status ->> 'membership_status'::TEXT,
        'membership_level', m.status ->> 'membership_level'::TEXT
    ),
    'access', json_build_object(
        'rfid_tags', m.access -> 'rfid_tags'::TEXT
    ),
    'authorizations', json_build_object(
        'physical_authorizations', m.authorizations -> 'authorizations'::TEXT,
        'computer_authorizations', m.authorizations -> 'computer_authorizations'::TEXT
    ),
    'extras', json_build_object(
        'storage_id', m.extras ->> 'storage_id'::TEXT,
        'essentials_form', m.extras ->> 'essentials_form'::TEXT,
        'orientation', m.extras ->> 'orientation'::TEXT,
        'ip_addresses', m.extras ->> 'ip_addresses'::TEXT,
        'storage_area', m.extras ->> 'storage_area'::TEXT)
) AS member_info
FROM   member m;
COMMENT ON VIEW v_member_info IS 'This view provides a structured JSON representation of member information, including identity, connections, forms, status, access, authorizations, and extras from the member table.';

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
COMMENT ON TABLE oauth2_users IS 'This table holds the OAuth2 client credentials for applications that need to access the Deep Harbor API.';

/* HEY! Update these with real client secrets using the generate_secret.sh tool! */
/* Our initial OAuth2 client for dev web services */
INSERT INTO oauth2_users (client_name, client_secret, client_description) VALUES ('dev-dhservices-v1', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'dev web services v1');
/* And another one for our admin portal */
INSERT INTO oauth2_users (client_name, client_secret, client_description) VALUES ('dev-admin-portal', '$2b$12$OcAzWAtVKG0oTtzeZeU42.SlZyABSOLF8153s/dX.yFaDsLDWNK46', 'admin portal application');
/* The member portal client */
insert into oauth2_users (client_name, client_secret, client_description) values('dev-member-portal', '$2b$12$17IgUjlVac/yIL4P6lBAlOed37uKM3qce9YgLIGFWhWRNLvU0bNES', 'member portal application');

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
 * Note we take bigint as input for convertfromwiegand because
 * the Wiegand 24-bit integer value can be larger than the
 * maximum value for a standard integer.
 */
CREATE FUNCTION convertfromwiegand (p_num bigint)  RETURNS integer
  VOLATILE
AS $body$
DECLARE
    v_baseVal varchar(20);  -- Increased from 8 to handle larger numbers
    v_facilityCode varchar(15);  -- Increased to handle larger facility codes
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
    -- Return NULL if input is NULL
    IF p_num IS NULL THEN
        RETURN NULL;
    END IF;
    
    v_baseVal := p_num::VARCHAR;
    
    -- Validate that we have at least 5 digits (for user code)
    IF length(v_baseVal) < 5 THEN
        --RAISE EXCEPTION 'Invalid Wiegand number: % (must be at least 5 digits)', p_num;
        RETURN NULL;
    END IF;

    -- We have to be careful about the facility code because it could be 
    -- three digits or less, while the user code will always be five
    -- digits
    v_facilityCode := substring(v_baseVal from 1 for length(v_baseVal) - 5);
    v_userCode := SUBSTRING(v_baseVal from length(v_baseVal) - 4);
    
    -- If facility code is empty (5-digit number), set it to '0'
    IF v_facilityCode = '' OR v_facilityCode IS NULL THEN
        v_facilityCode := '0';
    END IF;
    
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
COMMENT ON FUNCTION convertfromwiegand(BIGINT) IS 'Converts a Wiegand 24-bit integer value into the corresponding facility code and user code integer value.';

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
 * Full Text Search Function
 * This function performs full text search on member records across
 * all searchable columns (identity, connections, access, authorizations,
 * extras, notes) and returns results ranked by relevance.
 */
CREATE OR REPLACE FUNCTION search_members(search_query text)
RETURNS TABLE (
    id integer,
    identity jsonb,
    connections jsonb,
    status jsonb,
    access jsonb,
    authorizations jsonb,
    extras jsonb,
    notes jsonb,
    rank real
) AS $body$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.identity,
        m.connections,
        m.status,
        m.access,
        m.authorizations,
        m.extras,
        m.notes,
        ts_rank(
            (
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.identity, '["all"]')::text, '')) ||
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.connections, '["all"]')::text, '')) ||
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.access, '["all"]')::text, '')) ||
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.authorizations, '["all"]')::text, '')) ||
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.extras, '["all"]')::text, '')) ||
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.notes, '["all"]')::text, ''))
            ),
            plainto_tsquery('english', search_query)
        ) AS rank
    FROM member m
    WHERE 
        (
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.identity, '["all"]')::text, '')) ||
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.connections, '["all"]')::text, '')) ||
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.access, '["all"]')::text, '')) ||
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.authorizations, '["all"]')::text, '')) ||
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.extras, '["all"]')::text, '')) ||
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.notes, '["all"]')::text, ''))
        ) @@ plainto_tsquery('english', search_query)
    ORDER BY rank DESC;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION search_members(text) IS 'Performs full text search on member records across all searchable JSONB columns and returns results ranked by relevance.';

/*
 * Similar function to the one above, but used just for searching
 * the identity column.
 */
CREATE OR REPLACE FUNCTION search_members_by_identity(search_query text)
RETURNS TABLE (
    id integer,
    identity jsonb,
    rank real
) AS $body$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.identity,
        ts_rank(
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.identity, '["all"]')::text, '')),
            plainto_tsquery('english', search_query)
        ) AS rank
    FROM member m
    WHERE 
        to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.identity, '["all"]')::text, ''))
        @@ plainto_tsquery('english', search_query)
    ORDER BY rank DESC;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION search_members_by_identity(text) IS 'Performs full text search on the identity JSONB column of member records and returns results ranked by relevance.';

/*
 * This function is used for searching members by identity and access
 * (e.g., RFID tags) and returning full member records. This is used in
 * the admin portal so that an admin can search for a member by name or RFID tag
 */
CREATE OR REPLACE FUNCTION search_members_by_identity_and_access(search_query text)
RETURNS TABLE (
    id integer,
    identity jsonb,
    connections jsonb,
    status jsonb,
    access jsonb,
    authorizations jsonb,
    extras jsonb,
    notes jsonb,
    rank real
) AS $body$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.identity,
        m.connections,
        m.status,
        m.access,
        m.authorizations,
        m.extras,
        m.notes,
        ts_rank(
            (
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.identity, '["all"]')::text, '')) ||
                to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.access, '["all"]')::text, ''))
            ),
            plainto_tsquery('english', search_query)
        ) AS rank
    FROM member m
    WHERE 
        -- Full-text search on identity and access
        (
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.identity, '["all"]')::text, '')) ||
            to_tsvector('english', COALESCE(jsonb_to_tsvector('english', m.access, '["all"]')::text, ''))
        ) @@ plainto_tsquery('english', search_query)
        OR
        -- Pattern matching for numeric searches (handles RFID tags with/without leading zeros)
        (search_query ~ '^[0-9]+$' AND m.access::text ILIKE '%' || search_query || '%')
    ORDER BY rank DESC;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION search_members_by_identity_and_access(text) IS 'Performs full text search on the identity and access JSONB columns of member records and returns results ranked by relevance.';

/*
 * Function that returns full member records based on identity search
 */
CREATE OR REPLACE FUNCTION get_members_details_by_identity(search_name text)
RETURNS TABLE (
    id integer,
    identity jsonb,
    status jsonb,
    access jsonb,
    authorizations jsonb,
    extras jsonb,
    notes jsonb
) AS $body$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.identity,
        m.status,
        m.access,
        m.authorizations,
        m.extras,
        m.notes
    FROM member m
    WHERE m.id IN (
        SELECT s.id 
        FROM search_members_by_identity(search_name) s
    );
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION get_members_details_by_identity(text) IS 'Returns full member records (id, identity, status, access, authorizations, extras, notes) by searching the identity column. Uses search_members_by_identity to find matching member IDs. May return zero or more rows';

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
            date_added,
            last_updated_by 
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
            CURRENT_TIMESTAMP,
            new.last_updated_by 
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
 * If you're looking to add more columns to be monitored, just add them
 * to the function and the triggers below. 
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

CREATE TABLE IF NOT EXISTS available_authorizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    requires_login BOOLEAN NOT NULL DEFAULT FALSE);
COMMENT ON TABLE available_authorizations IS 'This table holds the authorization types (i.e. the various equipment authorizations) used in the Deep Harbor system.';
-- Hard-coded authorization types specific to the PS1 hackspace
-- as of December 2025
insert into available_authorizations (id, name, requires_login) values
        (1, 'Boss Authorized Users', true),
        (2, 'CNC Plasma Authorized Users', true),
        (3, 'Epilog Authorized Users', true),
        (4, 'ShopBot Authorized Users', true),
        (5, 'Tormach Authorized Users', true),
        (6, 'Universal Authorized Users', true),
        (7, 'Vinyl Cutter Authorized Users', true),
        (8, 'Mimaki CJV30 printer Users', true),
        (9, 'Band Saw', false),
        (10, 'Billiards', false),
        (11, 'Blacksmithing', false),
        (12, 'Bridgeport Mill', false),
        (13, 'Button sewing machines', false),
        (14, 'Clausing Lathe', false),
        (15, 'Coffee Roaster', false),
        (16, 'Cold Metals Basic', false),
        (17, 'Drum Sander', false),
        (18, 'Ender 3D Printers', false),
        (19, 'Formlabs Form 3 printer', false),
        (20, 'Hand held plasma cutter', false),
        (21, 'Jointer', false),
        (22, 'LeBlond Lathe', false),
        (23, 'Metal Band Saw', false),
        (24, 'Metal Drill Press', false),
        (25, 'Mig Welders', false),
        (26, 'Mitre Saw', false),
        (27, 'Multi-Router', false),
        (28, 'Panel Saw', false),
        (29, 'Planer', false),
        (30, 'Pneumatic Power Tools', false),
        (31, 'Powder Coating Equipment', false),
        (32, 'Prusa 3D printers', false),
        (33, 'Router Table', false),
        (34, 'Sanders', false),
        (35, 'Saw Dado', false),
        (36, 'Serger sewing machine', false),
        (37, 'Square Chisel Morticer', false),
        (38, 'Surface Grinder', false),
        (39, 'Table Saw', false),
        (40, 'Tier one Sewing Machine', false),
        (41, 'Tig Welders', false),
        (42, 'Tube Bending Equipment', false),
        (43, 'Wood Drill Press', false),
        (44, 'Wood Lathe', false),
        (45, 'Wood Mini Lathe', false);

/*
 * Activity tables
 */

-- This table logs member access of the doors using RFID tags.
CREATE TABLE IF NOT EXISTS member_access_log (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    member_id INTEGER REFERENCES member(id) ON DELETE SET NULL,
    rfid_tag TEXT NOT NULL,
    board_tag_num BIGINT NOT NULL,
    access_point TEXT NOT NULL,
    access_granted BOOLEAN NOT NULL,
    timestamp TIMESTAMP(6) WITHOUT TIME ZONE 
);
COMMENT ON TABLE member_access_log IS 'This table logs member access events (i.e. front door, back door) using RFID tags';

-- Unique index to prevent duplicate access log entries
CREATE UNIQUE INDEX IF NOT EXISTS idx_member_access_log_unique 
ON member_access_log (rfid_tag, board_tag_num, access_point, access_granted, timestamp);
COMMENT ON INDEX idx_member_access_log_unique IS 'This unique index ensures that duplicate access log entries are not created for the same RFID tag, board tag number, access point, access granted status, and timestamp combination.';

/* Helper function to find member by RFID tag */
CREATE OR REPLACE FUNCTION get_member_by_rfid_tag(p_tag_number BIGINT)
RETURNS TABLE (
    id INTEGER,
    first_name TEXT,
    last_name TEXT,
    email_address TEXT,
    tag_id BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_converted_tag BIGINT;
BEGIN
     -- Try to convert the tag number first, handle any errors
    BEGIN
        v_converted_tag := convertfromwiegand(p_tag_number);
    EXCEPTION WHEN OTHERS THEN
        -- If conversion fails, just use the original tag number
        RETURN QUERY
        SELECT NULL::INTEGER, NULL::TEXT, NULL::TEXT, NULL::TEXT, p_tag_number;
        RETURN;
    END;

    RETURN QUERY
    SELECT m.id, 
        m.identity ->> 'first_name' AS first_name,
        m.identity ->> 'last_name' AS last_name,
        m.identity -> 'emails' -> 0 ->> 'email_address' AS email_address,
        v_converted_tag AS tag_id
    FROM member m
    WHERE EXISTS (
        SELECT 1 
        FROM jsonb_array_elements_text(m.access->'rfid_tags') AS tag
        WHERE tag LIKE '%' || v_converted_tag::text || '%'
    );
    
    -- If no member was found, return a row with NULLs for member fields but with the converted tag
    IF NOT FOUND THEN
        RETURN QUERY
        SELECT NULL::INTEGER, NULL::TEXT, NULL::TEXT, NULL::TEXT, v_converted_tag;
    END IF;
END;
$$;
COMMENT ON FUNCTION get_member_by_rfid_tag(BIGINT) IS 'This function retrieves member details based on the provided RFID tag number by converting it from Wiegand format and searching the access->rfid_tags array in the member table.';

-- View to combine member access logs with member identity information
-- for things like reports or audits.
CREATE OR REPLACE VIEW v_member_access_log AS
SELECT mal.id,
       mal.timestamp,
       CASE 
           WHEN mal.access_point = '1' THEN 'Front Door'
           WHEN mal.access_point = '2' THEN 'Back Door'
           ELSE mal.access_point
       END AS access_point,
       mal.access_granted,
       mal.board_tag_num,
       convertfromwiegand(mal.board_tag_num) AS tag_num,
       m.id AS member_id,
       m.identity ->> 'first_name' AS first_name,
       m.identity ->> 'last_name' AS last_name,
       m.identity -> 'emails' -> 0 ->> 'email_address' AS email_address
FROM member_access_log mal
LEFT JOIN member m ON mal.member_id = m.id;
COMMENT ON VIEW v_member_access_log IS 'This view combines member access logs with member identity information for easier querying of access events along with basic member info.';

/*
 * Deep Harbor Care-n-Feeding DDL that revolves around administering 
 * members, equipment, auths, etc.
 */

CREATE TABLE roles (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
    NAME TEXT NOT NULL,
    permission JSONB NOT NULL,
    PRIMARY KEY (id)
);
COMMENT ON TABLE roles IS 'This table holds the various roles defined in the Deep Harbor system along with their associated permissions stored as JSONB.';

/* 
 * Some initial roles for Deep Harbor.
 * Note - these values are *not* arbitrary. They refer to the names of the panels 
 * in the DHAdminPortal interface. Check index.html in that project to see them in  
 * the filterTabsByPermissions() function.
 */
INSERT INTO roles (name, permission) VALUES ('Authorizer', '{"view": ["identity", "authorizations"], "change": ["authorizations"]}');
INSERT INTO roles (name, permission) VALUES ('Administrator', '{"view": ["identity", "status", "roles", "forms", "connections", "extras", "authorizations", "notes", "access", "entry"], "change": ["identity", "status", "roles", "forms", "connections", "extras", "authorizations", "notes", "access"]}');
INSERT into roles (name, permission) VALUES ('Board', '{"view": ["identity", "status", "notes", "entry"], "change": ["status", "notes"]}');

/* 
 * How we assign roles to members - note that Deep Harbor is written with the idea that anyone who is a 
 * member can have a role, the assumption that the membership is responsible for everything.
 */
CREATE TABLE member_to_role (
    role_id    INTEGER,
    member_id  INTEGER,
    date_added TIMESTAMP(6) WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT membertorole_fk1 FOREIGN KEY (role_id) REFERENCES "roles"
    ("id"),
    CONSTRAINT membertorole_fk2 FOREIGN KEY (member_id) REFERENCES "member"
    ("id") on delete cascade
);
COMMENT ON TABLE member_to_role IS 'This table maps members to their assigned roles in the Deep Harbor system, allowing for role-based access control.';

/*
 * User activity logging table - this logs user activity in the DH system
 */
CREATE TABLE user_activity_logs
(
    member_id     INTEGER NOT NULL,
    activity_details jsonb NOT NULL,
    TIMESTAMP TIMESTAMP(6) WITH TIME ZONE NOT NULL,
    CONSTRAINT useractivity_fk1 FOREIGN KEY (member_id) REFERENCES "member"
    ("id") on delete cascade
);
COMMENT ON TABLE user_activity_logs IS 'This table records user activity in the Deep Harbor system, recording member ID, timestamp, and page accessed for auditing purposes.';

-- RFID Board Sync table - this tracks the last sync timestamp for the RFID board so that
-- we can avoid long sync times.
CREATE TABLE rfid_board_sync
(
    position INTEGER NOT NULL,
    TIMESTAMP TIMESTAMP(6) WITH TIME ZONE NOT NULL
);
COMMENT ON TABLE rfid_board_sync IS 'This table tracks the last synchronization position in its database for the RFID board used by PS1.';

/*
 * WaiverForever Integration Table
 */

-- PS1 uss WaiverForever for member waivers. This table stores
-- the waiver details received from WaiverForever webhooks and acts
-- as a record of waivers on file.
CREATE TABLE waivers
(
    id INTEGER NOT NULL GENERATED ALWAYS AS identity,
    details jsonb NOT NULL,
    date_added TIMESTAMP WITH TIME zone DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);
COMMENT ON TABLE waivers IS 'This table stores waiver details received from WaiverForever webhooks, including the waiver data in JSONB format and the date it was added.';

-- View to simplify querying waiver details
CREATE OR REPLACE VIEW v_waivers AS
    SELECT DISTINCT 
    ON (first_name, 
            last_name, 
            email_address, 
            phone_number) id,
            first_name,
            last_name,
            email_address,
            phone_number,
            signed_at_datetime,            
            date_added
    FROM     ( SELECT waivers.id, ( SELECT jsonb_array_elements.value ->> 'first_name'::TEXT
                    FROM    jsonb_array_elements((waivers.details -> 'content'::TEXT) -> 'data'::TEXT) 
                            jsonb_array_elements(value)
                    WHERE   (jsonb_array_elements.value ->> 'type':: TEXT) = 'name_field'::TEXT 
                    AND     (jsonb_array_elements.value ->> 'title'::TEXT) = 'Name'::TEXT
                    LIMIT   1) AS first_name, ( SELECT jsonb_array_elements.value ->> 'last_name':: 
                            TEXT
                    FROM    jsonb_array_elements((waivers.details -> 'content'::TEXT) -> 'data'::TEXT) 
                            jsonb_array_elements(value)
                    WHERE   (jsonb_array_elements.value ->> 'type':: TEXT) = 'name_field'::TEXT 
                    AND     (jsonb_array_elements.value ->> 'title'::TEXT) = 'Name'::TEXT
                    LIMIT   1) AS last_name, ( SELECT jsonb_array_elements.value ->> 'value'::TEXT
                    FROM    jsonb_array_elements((waivers.details -> 'content'::TEXT) -> 'data'::TEXT) 
                            jsonb_array_elements(value)
                    WHERE   (jsonb_array_elements.value ->> 'type'::TEXT) = 'email_field'::TEXT
                    LIMIT   1) AS email_address, ( SELECT jsonb_array_elements.value ->> 'value'::TEXT
                    FROM    jsonb_array_elements((waivers.details -> 'content'::TEXT) -> 'data'::TEXT) 
                            jsonb_array_elements(value)
                    WHERE   (jsonb_array_elements.value ->> 'type':: TEXT) = 'phone_field'::TEXT 
                    AND     (jsonb_array_elements.value ->> 'title'::TEXT) = 'Phone number'::TEXT
                    LIMIT   1) AS phone_number,                     
                    TO_TIMESTAMP(
                        (waivers.details -> 'content' ->> 'signed_at')::BIGINT
                    ) AS signed_at_datetime,
                    waivers.date_added
            FROM    waivers) waiver_data
    ORDER BY first_name, 
            last_name, 
            email_address, 
            phone_number, 
            date_added DESC;
COMMENT ON VIEW v_waivers IS 'This view simplifies querying waiver details by extracting first name, last name, email address, phone number, and signed at datetime from the waivers table, returning the most recent waiver for each unique combination of these fields.';
