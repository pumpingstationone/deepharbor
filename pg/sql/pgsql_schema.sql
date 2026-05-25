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

-- Helper view to get the primary email for a member
create view v_member_id_email AS
SELECT id,
       jsonb_path_query_first( identity, '$.emails[*] ? (@.type == "primary").email_address' )#>>
       '{}' AS primary_email
FROM   member;
COMMENT ON VIEW v_member_id_email IS 'This view provides a list of member IDs along with their primary email address';

-- Member names and status view
CREATE VIEW v_member_names_and_status AS
SELECT id, 
       identity->>'first_name' AS first_name, 
       identity->>'last_name' AS last_name,
       status->>'membership_status' AS membership_status
FROM   member;
COMMENT ON VIEW v_member_names_and_status IS 'This view provides a list of member IDs along with their first name, last name, and membership status from the member table.';

-- Similar to v_member_names_and_status but also includes the primary email address for each member, 
-- which is extracted from the identity JSONB column. This is useful for reports or queries where you 
-- want to see the member''s name, email, and status together without having to write the JSONB 
-- extraction logic each time.
create view v_member_name_email_status as
SELECT id,
       identity ->> 'first_name':: TEXT AS first_name,
       identity ->> 'last_name'::  TEXT AS last_name,
       jsonb_path_query_first( identity, '$.emails[*] ? (@.type == "primary").email_address' )#>>
       '{}' AS primary_email,
       status ->> 'membership_status'::TEXT AS membership_status
FROM   member;
COMMENT ON VIEW v_member_name_email_status IS 'This view provides a list of member IDs along with their first name, last name, primary email address, and membership status from the member table.';

-- This view wraps most of the member data for easier querying
-- and displaying on the member portal
CREATE OR REPLACE VIEW v_member_info as
SELECT m.id member_id, 
json_build_object(
    'identity', json_build_object(
        'member_id', m.id,
        'first_name', m.identity ->> 'first_name'::TEXT,
        'last_name', m.identity ->> 'last_name'::TEXT,
        'primary_email', jsonb_path_query_first( m.identity, '$.emails[*] ? (@.type == "primary").email_address' )#>>'{}',
        'nickname', m.identity ->> 'nickname'::TEXT,
        'active_directory_username', m.identity ->> 'active_directory_username'::TEXT,
        'pronouns', m.identity ->> 'pronouns'::TEXT,
        'nametag_subtitle', m.identity ->> 'nametag_subtitle'::TEXT,
        'theme_song_url', m.identity ->> 'theme_song_url'::TEXT,
        'theme_song_duration', m.identity ->> 'theme_song_duration'::TEXT
    ),
    'connections', json_build_object(
      'discord_username', m.connections ->> 'discord_username'::TEXT
    ),
    'forms', json_build_object(
        'id_check_1', m.forms ->> 'id_check_1'::TEXT,
        'id_check_2', m.forms ->> 'id_check_2'::TEXT,
        -- Bad/empty values in id_check_date / id_check_by would otherwise
        -- poison the entire v_member_info read (issue #75 territory). The
        -- regex shape-checks here gracefully NULL them instead.
        'id_check_date', CASE WHEN m.forms ->> 'id_check_date' ~ '^\d{4}-\d{2}-\d{2}$'
                              THEN to_date(m.forms ->> 'id_check_date', 'YYYY-MM-DD')
                              ELSE NULL END,
        'id_check_by',   CASE WHEN m.forms ->> 'id_check_by' ~ '^[0-9]+$'
                              THEN (m.forms ->> 'id_check_by')::INT
                              ELSE NULL END,
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
/* The Stripe integration client */
insert into oauth2_users (client_name, client_secret, client_description) values('dev-stripe-client', '$2b$12$unL07f/9iLD1OOqhZR9dPuFIOMcEk/MhLDh667rWhmHCnik4E7pF6', 'Stripe integration for membership payments');
/* DHStatus to DH2MG to send emails */
insert into oauth2_users (client_name, client_secret, client_description) values ('dev-mail-client', '$2b$12$V8Dikb9vM7NifiNo.CaRCumI6coyAWEWBKCflsDtqDPO9TKO58J3q', 'status service to dh2mg for sending emails');


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

CREATE OR REPLACE FUNCTION converttowiegand (p_num bigint)  RETURNS integer
  VOLATILE
AS $body$
DECLARE
    v_baseVal VARCHAR(24) := '';
    v_fc VARCHAR(8) := '';
    v_uc VARCHAR(16) := '';

    v_fNum INTEGER;
    v_uNum INTEGER;
    v_uPadNum varchar(5);

    v_FinalNum varchar(16) := '';
BEGIN
    -- Return NULL if input is NULL
    IF p_num IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Convert the number passed to us as a binary string
    v_baseVal := CAST(p_num::bit(24)::VARCHAR AS VARCHAR(24));

    -- Validate that we have at least 5 digits (for user code)
    IF length(v_baseVal) < 5 THEN
        --RAISE EXCEPTION 'Invalid Wiegand number: % (must be at least 5 digits)', p_num;
        RETURN NULL;
    END IF;

    -- Okay, we need two parts, the facility code, and the user code
    v_fc := SUBSTRING(v_baseVal from 1 for 8);
    v_uc := SUBSTRING(v_baseVal from 9);
    
    -- Now we're going to convert the bits to numbers
    v_fNum := (v_fc::bit(8))::integer;
    v_uNum := (v_uc::bit(16))::integer;
    
    v_uPadNum := lpad(v_uNum::varchar, 5, '0');
  
    -- And put it all together    
    v_FinalNum := format('%s%s', v_fNum::varchar, v_uPadNum);
  
    RETURN (SELECT v_FinalNum::integer);
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION converttowiegand(bigint) IS 'Converts a facility code and user code integer value into the corresponding Wiegand 24-bit integer value.';

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
                 converttowiegand(at.tag::BIGINT) WIEGAND_TAG_NUM,
                 CASE
                          WHEN EXISTS (    SELECT 1
                                           FROM    member m
                                           WHERE   m.id = p_member_id
                                           AND     m.access->'rfid_tags' @> ('["' || at.tag || '"]')::jsonb )
                          THEN 'ACTIVE'
                          ELSE 'INACTIVE'
                 END AS status
        FROM     all_tags at
        WHERE    at.tag IS NOT NULL
        AND      TRIM(at.tag) <> ''
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
BEGIN
    -- Insert one member_changes row per changed column so each gets its own
    -- 'change' key and DHDispatcher can route them independently.

    IF TG_OP = 'INSERT' THEN
        IF NEW.identity IS NOT NULL THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'identity', 'identity', NEW.identity));
        END IF;
        IF NEW.status IS NOT NULL THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'status', 'status', NEW.status));
        END IF;
        IF NEW.access IS NOT NULL THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'access', 'access', NEW.access));
        END IF;
        IF NEW.authorizations IS NOT NULL THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'authorizations', 'authorizations', NEW.authorizations));
        END IF;
    ELSE
        -- UPDATE operation - only log changed columns
        IF NEW.identity IS DISTINCT FROM OLD.identity THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'identity', 'identity', NEW.identity));
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'status', 'status', NEW.status));
        END IF;
        IF NEW.access IS DISTINCT FROM OLD.access THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'access', 'access', NEW.access));
        END IF;
        IF NEW.authorizations IS DISTINCT FROM OLD.authorizations THEN
            INSERT INTO member_changes (member_id, data)
            VALUES (NEW.id, jsonb_build_object('member_id', NEW.id, 'change', 'authorizations', 'authorizations', NEW.authorizations));
        END IF;
    END IF;

    RETURN NEW;
END;
$body$ LANGUAGE plpgsql;
COMMENT ON FUNCTION log_member_changes() IS 'This function logs changes to monitored columns (identity, status, access, authorizations) in the member table. Each changed column gets its own member_changes row so DHDispatcher can route them independently.';

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

-- The available_authorizations table holds the various authorization types (e.g. equipment authorizations) 
-- that can be assigned to members in the system. This is used as a lookup table for the authorizations JSONB 
-- column in the member table, as well as for managing authorization types in the admin portal.
-- Note that the 'requires_login' field indicates whether this authorization type requires the member to be 
-- in a particular OU to be able to log into a particular computer.
-- PS1 currently has an OU for _all_ items, so theoretically this field is redundant, but we still use
-- it in case some future system that we don't know about needs to be able to differentiate between 
-- login-required and non-login-required authorizations. For example, we might have some future piece of 
-- software that only cares about equipment authorizations and not general member authorizations, and it 
-- could use this field to filter out the non-login-required authorizations.
-- TL;DR: we include the 'requires_login' field for future flexibility even though it's not strictly necessary 
-- for our current use case.
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

-- This function compares the current authorizations of a member with the previous version 
-- in the member_audit table and returns a JSONB object containing the member_id, added authorizations, 
-- and removed authorizations.
-- Note that it compares the current state of the member record with the previous version in the 
-- member_audit table, so it will show what has changed from the last version to the current version. 
-- If you want to compare two arbitrary versions, you would need to modify the function to take additional 
-- parameters for the versions to compare.
CREATE OR REPLACE FUNCTION get_authorization_changes_for_member(member_id integer)
RETURNS jsonb AS $$
  WITH current_data AS (
    SELECT 
      id,
      'authorizations' AS auth_type,
      jsonb_array_elements_text(authorizations->'authorizations') AS auth
    FROM member
    WHERE id = member_id
    UNION ALL
    SELECT 
      id,
      'computer_authorizations' AS auth_type,
      jsonb_array_elements_text(authorizations->'computer_authorizations') AS auth
    FROM member
    WHERE id = member_id
  ),
  audit_data AS (
    SELECT 
      member_audit.id,
      'authorizations' AS auth_type,
      jsonb_array_elements_text(authorizations->'authorizations') AS auth
    FROM member_audit
    WHERE member_audit.id = member_id
      AND version = (
        SELECT MAX(version) - 1
        FROM member_audit 
        WHERE member_audit.id = member_id
      )
    UNION ALL
    SELECT 
      member_audit.id,
      'computer_authorizations' AS auth_type,
      jsonb_array_elements_text(authorizations->'computer_authorizations') AS auth
    FROM member_audit
    WHERE member_audit.id = member_id
      AND version = (
        SELECT MAX(version) - 1
        FROM member_audit 
        WHERE member_audit.id = member_id
      )
  ),
  added AS (
    SELECT auth_type, auth
    FROM current_data
    WHERE (auth_type, auth) NOT IN (SELECT auth_type, auth FROM audit_data)
  ),
  removed AS (
    SELECT auth_type, auth
    FROM audit_data
    WHERE (auth_type, auth) NOT IN (SELECT auth_type, auth FROM current_data)
  )
  SELECT jsonb_build_object(
    'member_id', member_id,
    'added', jsonb_build_object(
      'authorizations', COALESCE((SELECT jsonb_agg(auth) FROM added WHERE auth_type = 'authorizations'), '[]'::jsonb),
      'computer_authorizations', COALESCE((SELECT jsonb_agg(auth) FROM added WHERE auth_type = 'computer_authorizations'), '[]'::jsonb)
    ),
    'removed', jsonb_build_object(
      'authorizations', COALESCE((SELECT jsonb_agg(auth) FROM removed WHERE auth_type = 'authorizations'), '[]'::jsonb),
      'computer_authorizations', COALESCE((SELECT jsonb_agg(auth) FROM removed WHERE auth_type = 'computer_authorizations'), '[]'::jsonb)
    )
  );
$$ LANGUAGE sql;
COMMENT ON FUNCTION get_authorization_changes_for_member(integer) IS 'This function compares the current authorizations of a member with the previous version in the member_audit table and returns a JSONB object containing the member_id, added authorizations, and removed authorizations.';

-- This function takes a member's authorizations JSONB object and returns a new JSONB object categorizing 
-- each available authorization as either "authorized" or "not_authorized" based on whether it is present 
-- in the member's authorizations.
-- This is a different take on the get_authorization_changes_for_member function above - instead of comparing 
-- current vs previous authorizations, it just categorizes all available authorizations based on whether the 
-- member currently has them or not. This is used by the DHAuthorizations service to show the full list of 
-- authorizations with their current status for a given member, which we pass on to DH2AD to manage 
-- Active Directory OUs.
CREATE OR REPLACE FUNCTION get_member_authorization_status(member_auths jsonb)
RETURNS jsonb AS $$
  WITH all_auths AS (
    SELECT 
      name,
      requires_login,
      CASE 
        WHEN requires_login THEN 'computer_authorizations'
        ELSE 'authorizations'
      END AS auth_type
    FROM available_authorizations
  ),
  member_auths_expanded AS (
    SELECT 
      'authorizations' AS auth_type,
      jsonb_array_elements_text(member_auths->'authorizations') AS auth_name
    UNION ALL
    SELECT 
      'computer_authorizations' AS auth_type,
      jsonb_array_elements_text(member_auths->'computer_authorizations') AS auth_name
  ),
  categorized AS (
    SELECT 
      a.name,
      a.auth_type,
      CASE 
        WHEN m.auth_name IS NOT NULL THEN 'authorized'
        ELSE 'not_authorized'
      END AS status
    FROM all_auths a
    LEFT JOIN member_auths_expanded m 
      ON a.name = m.auth_name AND a.auth_type = m.auth_type
  )
  SELECT jsonb_build_object(
    'authorized', jsonb_build_object(
      'authorizations', COALESCE(
        (SELECT jsonb_agg(name ORDER BY name) 
         FROM categorized 
         WHERE status = 'authorized' AND auth_type = 'authorizations'), 
        '[]'::jsonb
      ),
      'computer_authorizations', COALESCE(
        (SELECT jsonb_agg(name ORDER BY name) 
         FROM categorized 
         WHERE status = 'authorized' AND auth_type = 'computer_authorizations'), 
        '[]'::jsonb
      )
    ),
    'not_authorized', jsonb_build_object(
      'authorizations', COALESCE(
        (SELECT jsonb_agg(name ORDER BY name) 
         FROM categorized 
         WHERE status = 'not_authorized' AND auth_type = 'authorizations'), 
        '[]'::jsonb
      ),
      'computer_authorizations', COALESCE(
        (SELECT jsonb_agg(name ORDER BY name) 
         FROM categorized 
         WHERE status = 'not_authorized' AND auth_type = 'computer_authorizations'), 
        '[]'::jsonb
      )
    )
  );
$$ LANGUAGE sql;
COMMENT ON FUNCTION get_member_authorization_status(jsonb) IS 'This function takes a member''s authorizations JSONB object and returns a new JSONB object categorizing each available authorization as either "authorized" or "not_authorized" based on whether it is present in the member''s authorizations.';

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
INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (1, 'Authorizer', '{"view": ["member.identity", "member.authorizations", "member.notes"], "change": ["member.authorizations", "member.notes"]}');
INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (2, 'Administrator', '{"view": ["member.identity", "member.status", "member.roles", "member.forms", "member.connections", "member.extras", "member.authorizations", "member.notes", "member.access", "member.entry", "space.access_logs", "systems.roles", "systems.assign_roles", "equipment.areas", "equipment.items", "equipment.groups", "equipment.tickets", "equipment.schedules", "equipment.auth_sessions", "equipment.maintenance", "equipment.dashboard", "equipment.config"], "change": ["member.identity", "member.status", "member.roles", "member.forms", "member.connections", "member.extras", "member.authorizations", "member.notes", "member.access", "systems.roles", "systems.assign_roles", "equipment.areas", "equipment.items", "equipment.groups", "equipment.tickets", "equipment.schedules", "equipment.auth_sessions", "equipment.maintenance", "equipment.config"]}');
INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (3, 'Board', '{"view": ["member.identity", "member.status", "member.notes", "member.entry"], "change": ["member.status", "member.notes"]}');
INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (4, 'Just Forms', '{"view": ["member.forms"], "change": ["member.forms"]}');
INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (5, 'SuperAdmin', '{"view": ["member.identity", "member.status", "member.roles", "member.forms", "member.connections", "member.extras", "member.authorizations", "member.notes", "member.access", "member.entry", "space.access_logs", "systems.roles", "systems.assign_roles", "equipment.areas", "equipment.items", "equipment.groups", "equipment.tickets", "equipment.schedules", "equipment.auth_sessions", "equipment.maintenance", "equipment.dashboard", "equipment.config"], "change": ["member.identity", "member.status", "member.roles", "member.forms", "member.connections", "member.extras", "member.authorizations", "member.notes", "member.access", "systems.roles", "systems.assign_roles", "equipment.areas", "equipment.items", "equipment.groups", "equipment.tickets", "equipment.schedules", "equipment.auth_sessions", "equipment.maintenance", "equipment.config"]}');
INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (6, 'just-space-logs', '{"view": ["space.access_logs"], "change": []}');
SELECT setval(pg_get_serial_sequence('roles', 'id'), (SELECT MAX(id) FROM roles));

/*
 * How we assign roles to members - note that Deep Harbor is written with the idea that anyone who is a 
 * member can have a role, the assumption that the membership is responsible for everything.
 */
CREATE TABLE member_to_role (
    role_id    INTEGER NOT NULL,
    member_id  INTEGER NOT NULL,
    date_added TIMESTAMP(6) WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT membertorole_fk1 FOREIGN KEY (role_id) REFERENCES "roles"
    ("id"),
    CONSTRAINT membertorole_fk2 FOREIGN KEY (member_id) REFERENCES "member"
    ("id") on delete cascade
);
COMMENT ON TABLE member_to_role IS 'This table maps members to their assigned roles in the Deep Harbor system, allowing for role-based access control.';

-- Unique index to prevent duplicate role assignments for the same member
ALTER TABLE member_to_role ADD CONSTRAINT membertorole_ix1 UNIQUE ("role_id", "member_id");


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

/*
 * Stripe Integration Tables
 */
CREATE TABLE subscriptions
(
  id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY,
  details jsonb NOT NULL,
  date_added TIMESTAMP WITH TIME zone DEFAULT now() NOT NULL,
  PRIMARY KEY (id)
);
COMMENT ON TABLE subscriptions IS 'This table stores subscription details received from Stripe webhooks via ST2DH, including the subscription data in JSONB format and the date it was added.';

-- View to extract relevant subscription event details from the subscriptions table and join it with member information
CREATE OR REPLACE VIEW v_subscription_events AS
SELECT   m.id AS member_id,
         m.identity->>'first_name' AS first_name,
         m.identity->>'last_name' AS last_name, ( SELECT elem->>'email_address'
         FROM    jsonb_array_elements(m.identity->'emails') AS elem
         WHERE   elem->>'type' = 'primary'
         LIMIT   1 ) AS email, s.id AS sub_event_id, (s.details #>> '{}')::jsonb ->> 'id' AS 
         event_id, (s.details #>> '{}') ::jsonb -> 'data' -> 'object' ->> 'customer' AS customer_id 
         , (s.details #>> '{}'):: jsonb -> 'data' -> 'object' ->> 'id' AS subscription_id, 
         (s.details #>> '{}')::jsonb -> 'data' -> 'object' -> 'plan' ->> 'product' AS product_id, 
         (s.details #>> '{}')::jsonb -> 'type' AS event_type
FROM     subscriptions s
JOIN     member m ON m.connections->>'stripe_id' = (s.details #>> '{}')::jsonb -> 'data' ->
         'object' ->> 'customer'
ORDER BY s.date_added;
COMMENT ON VIEW v_subscription_events IS 'This view extracts relevant subscription event details from the subscriptions table and joins it with member information to provide a comprehensive view of subscription events, including member name, email, event ID, customer ID, subscription ID, product ID, and event type.';

-- Products table to store details about the products that members can subscribe to. 
-- This is used in conjunction with the Stripe integration to manage subscriptions and billing.
CREATE TABLE products
(
    id              INTEGER NOT NULL GENERATED ALWAYS AS identity,
    name            TEXT NOT NULL,
    details         jsonb NOT NULL,
    description     TEXT,
    date_added      TIMESTAMP WITH TIME zone DEFAULT now() NOT NULL,
    date_modified   TIMESTAMP WITH TIME zone DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);
COMMENT ON TABLE products IS 'This table stores details about the products that members can subscribe to.';

-- And let's insert some initial products that correspond to the membership types we have in the system, 
-- so that we can link them to Stripe products for billing purposes.
-- Note the stripe_product_id is specific to a test Stripe environment and will need to be updated for 
-- production use. (This is left as an exercise for the reader to set up your own Stripe products and 
-- update these values accordingly)
INSERT INTO products (name, details, description) VALUES ('Basic Membership', '{"stripe_product_id": "prod_Tws7udZJSXI9DU"}', 'Basic membership without storage');
INSERT INTO products (name, details, description) VALUES ('Membership with Storage', '{"stripe_product_id": "prod_TwsAMgaH3iLJ9c"}', 'Membership with storage');


/*
 * Email Templates Table
 * This table stores email templates that can be used for various 
 * notifications in the system, such as membership renewal reminders, 
 * event notifications, etc. The 'use_for' field indicates what the 
 * template is used for (e.g. 'membership_renewal', 'event_notification', 
 * etc.) so that the system can select the appropriate template when 
 * sending emails.
 */
CREATE TABLE email_templates
(
    id            INTEGER NOT NULL GENERATED ALWAYS AS identity,
    name          TEXT NOT NULL,
    use_for       TEXT NOT NULL,
    subject       TEXT NOT NULL,
    date_added    TIMESTAMP WITH TIME zone DEFAULT now() NOT NULL,
    date_modified TIMESTAMP WITH TIME zone DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);
COMMENT ON TABLE email_templates IS 'This table stores email templates that can be used for various notifications in the system, such as membership renewal reminders, event notifications, etc. The ''use_for'' field indicates what the template is used for (e.g. ''membership_renewal'', ''event_notification'', etc.) so that the system can select the appropriate template when sending emails.';

-- Sample data
insert into email_templates (name, use_for, subject) values ('dh-welcome-to-ps1', 'Pending membership', 'Welcome to PS1!');
insert into email_templates (name, use_for, subject) values ('dh-you-are-now-a-member', 'Active membership', 'You are now a PS1 member!');
insert into email_templates (name, use_for, subject) values ('dh-happy-trails-to-you', 'Inactive membership', 'Happy trails to you!');


-- And this table defines the parameters that can be used in the email templates, 
-- including the parameter name, type, whether it is required, default value, 
-- and description. It references the email_templates table to associate parameters 
-- with specific templates.
CREATE TABLE email_template_parameters (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES email_templates(id),
    parameter_name VARCHAR(100) NOT NULL,
    parameter_type VARCHAR(50),
    is_required BOOLEAN DEFAULT true,
    default_value TEXT,
    description TEXT
);
COMMENT ON TABLE email_template_parameters IS 'This table defines the parameters that can be used in email templates, including the parameter name, type, whether it is required, default value, and description. It references the email_templates table to associate parameters with specific templates.';
CREATE INDEX idx_template_params ON email_template_parameters(template_id);

-- Sample data for email template parameters
-- (assumes the sample email templates inserted above have IDs 1, 2, and 3 respectively)
insert into email_template_parameters (template_id, parameter_name, parameter_type) values(1, 'first_name', 'string');
insert into email_template_parameters (template_id, parameter_name, parameter_type) values(2, 'first_name', 'string');
insert into email_template_parameters (template_id, parameter_name, parameter_type) values(3, 'first_name', 'string');
insert into email_template_parameters (template_id, parameter_name, parameter_type) values(3, 'email_address', 'string');


/************************************************************************
 *
 * Equipment Module
 * 
 * These tables support the Deep Harbor Equipment Management module,
 * adapted from the Purple Asset One (PA1) project. This module provides
 * equipment inventory, repair ticketing, scheduling, authorization
 * sessions, maintenance tracking, and equipment grouping.
 *
 ***********************************************************************/


/* =====================================================================
 * Equipment Module Roles
 * =====================================================================
 * Area Host: can view and manage equipment, areas, tickets, schedules,
 *   auth sessions, and maintenance. Also has member-level access for
 *   identity, authorizations, and notes.
 * Technician: similar view access but more limited change permissions —
 *   equipment items, tickets, schedules, maintenance only.
 * ===================================================================== */

INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (
    7, 'Area Host',
    '{
        "view": [
            "member.identity", "member.authorizations", "member.notes",
            "equipment.areas", "equipment.items", "equipment.groups",
            "equipment.tickets", "equipment.schedules", "equipment.auth_sessions",
            "equipment.maintenance", "equipment.dashboard"
        ],
        "change": [
            "member.authorizations", "member.notes",
            "equipment.areas", "equipment.items", "equipment.groups",
            "equipment.tickets", "equipment.schedules", "equipment.auth_sessions",
            "equipment.maintenance"
        ]
    }'
);

INSERT INTO roles (id, name, permission) OVERRIDING SYSTEM VALUE VALUES (
    8, 'Technician',
    '{
        "view": [
            "member.identity", "member.authorizations", "member.notes",
            "equipment.areas", "equipment.items", "equipment.groups",
            "equipment.tickets", "equipment.schedules", "equipment.auth_sessions",
            "equipment.maintenance", "equipment.dashboard"
        ],
        "change": [
            "member.notes",
            "equipment.items", "equipment.tickets",
            "equipment.schedules", "equipment.maintenance"
        ]
    }'
);

SELECT setval(pg_get_serial_sequence('roles', 'id'), (SELECT MAX(id) FROM roles));


/* =====================================================================
 * Areas
 * =====================================================================
 * Named zones within the space (e.g. Woodshop, Electronics, CNC).
 * Named generically as "areas" for future reuse beyond equipment.
 * The metadata JSONB field stores contact info, website, discord, etc.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS areas (
    id          INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    metadata    JSONB DEFAULT '{}',
    attachments JSONB DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE areas IS 'Named zones within the space (e.g. Woodshop, Electronics). Used by the equipment module and potentially other modules in the future.';


/* =====================================================================
 * Equipment
 * =====================================================================
 * Main equipment inventory table. Tracks make, model, serial number,
 * status, and custom attributes. The electrical and breaker JSONB
 * columns store structured power specs and circuit location data.
 *
 * electrical example:
 *   {"voltage": 240, "amperage": 30, "phase": "single",
 *    "plug_type": "NEMA 6-30P", "notes": "Requires dedicated circuit"}
 *
 * breaker example:
 *   {"panel": "B", "breaker_number": 14,
 *    "location_description": "North wall, behind the CNC area",
 *    "notes": "Shared circuit with dust collector"}
 *
 * The version column supports optimistic locking — the auto-update
 * trigger increments it on every UPDATE.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS equipment (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    area_id         INTEGER REFERENCES areas(id) ON DELETE SET NULL,
    common_name     TEXT,
    make            TEXT NOT NULL,
    model           TEXT NOT NULL,
    serial_number   TEXT UNIQUE NOT NULL,
    build_date      DATE,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'inactive', 'under_repair', 'decommissioned')),
    schedulable     BOOLEAN DEFAULT FALSE,
    electrical      JSONB DEFAULT '{}',
    breaker         JSONB DEFAULT '{}',
    attributes      JSONB DEFAULT '{}',
    attachments     JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    version         INTEGER DEFAULT 1
);
COMMENT ON TABLE equipment IS 'Main equipment inventory. Tracks identity, status, power requirements, and custom attributes. Version column supports optimistic locking.';
CREATE INDEX idx_equipment_area ON equipment(area_id);
CREATE INDEX idx_equipment_status ON equipment(status);
CREATE INDEX idx_equipment_attributes ON equipment USING GIN(attributes);


/* =====================================================================
 * Equipment Groups
 * =====================================================================
 * Organize related equipment together (e.g. "All 3D Printers",
 * "Woodshop Saws"). A junction table links equipment to groups
 * with an optional sort order.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS equipment_groups (
    id          INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name        TEXT NOT NULL,
    description TEXT,
    area_id     INTEGER REFERENCES areas(id) ON DELETE SET NULL,
    attachments JSONB DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE equipment_groups IS 'Groups of related equipment for organizational purposes. Equipment can belong to multiple groups.';

CREATE TABLE IF NOT EXISTS equipment_group_members (
    group_id     INTEGER NOT NULL REFERENCES equipment_groups(id) ON DELETE CASCADE,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    sort_order   INTEGER DEFAULT 0,
    PRIMARY KEY (group_id, equipment_id)
);
COMMENT ON TABLE equipment_group_members IS 'Junction table linking equipment to groups with optional sort ordering.';


/* =====================================================================
 * Repair Tickets
 * =====================================================================
 * Linked to equipment. Auto-generated ticket numbers (TKT-001000, etc.)
 * via a sequence. Tracks status workflow, priority, work log entries,
 * parts used, and file attachments. The opened_by and assigned_to
 * columns reference DH member IDs.
 * ===================================================================== */

CREATE SEQUENCE IF NOT EXISTS ticket_seq START 1000;

CREATE OR REPLACE FUNCTION next_ticket_number()
RETURNS TEXT AS $$
BEGIN
    RETURN 'TKT-' || LPAD(nextval('ticket_seq')::TEXT, 6, '0');
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS repair_tickets (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    equipment_id    INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    ticket_number   TEXT UNIQUE NOT NULL DEFAULT next_ticket_number(),
    opened_by       INTEGER REFERENCES member(id),
    assigned_to     INTEGER REFERENCES member(id),
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'on_hold', 'closed')),
    priority        TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    title           TEXT NOT NULL,
    description     TEXT,
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    work_log        JSONB DEFAULT '[]',
    parts_used      JSONB DEFAULT '[]',
    attachments     JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    category        TEXT NOT NULL DEFAULT 'repair'
                    CHECK (category IN ('repair', 'maintenance')),
    version         INTEGER DEFAULT 1
);
COMMENT ON TABLE repair_tickets IS 'Repair and maintenance tickets linked to equipment. Auto-generated ticket numbers, status workflow, work log, and file attachments.';
CREATE INDEX idx_tickets_equipment ON repair_tickets(equipment_id);
CREATE INDEX idx_tickets_status ON repair_tickets(status);
CREATE INDEX idx_tickets_assigned ON repair_tickets(assigned_to);


/* =====================================================================
 * Maintenance Schedules & Events
 * =====================================================================
 * maintenance_schedules defines recurring tasks targeting either a
 * specific piece of equipment or an equipment group. The constraint
 * ensures at least one target is set.
 *
 * maintenance_events are individual instances generated from a schedule.
 * They track completion status and can optionally link to a repair
 * ticket if the maintenance work requires one.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS maintenance_schedules (
    id                  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    title               TEXT NOT NULL,
    description         TEXT,
    equipment_id        INTEGER REFERENCES equipment(id) ON DELETE CASCADE,
    group_id            INTEGER REFERENCES equipment_groups(id) ON DELETE CASCADE,
    recurrence_type     TEXT NOT NULL DEFAULT 'days'
                        CHECK (recurrence_type IN ('days', 'weeks', 'months', 'years')),
    recurrence_interval INTEGER NOT NULL DEFAULT 30,
    assigned_to         INTEGER REFERENCES member(id) ON DELETE SET NULL,
    created_by          INTEGER NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    priority            TEXT NOT NULL DEFAULT 'normal'
                        CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    estimated_minutes   INTEGER,
    checklist           JSONB DEFAULT '[]',
    notify_roles        TEXT[] DEFAULT '{}',
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT maint_sched_target CHECK (equipment_id IS NOT NULL OR group_id IS NOT NULL)
);
COMMENT ON TABLE maintenance_schedules IS 'Recurring maintenance task definitions. Each schedule targets either a specific equipment item or an equipment group.';

CREATE TABLE IF NOT EXISTS maintenance_events (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    schedule_id     INTEGER NOT NULL REFERENCES maintenance_schedules(id) ON DELETE CASCADE,
    equipment_id    INTEGER REFERENCES equipment(id) ON DELETE CASCADE,
    due_date        TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped', 'overdue')),
    assigned_to     INTEGER REFERENCES member(id) ON DELETE SET NULL,
    completed_by    INTEGER REFERENCES member(id) ON DELETE SET NULL,
    completed_at    TIMESTAMPTZ,
    notes           TEXT,
    checklist_state JSONB DEFAULT '[]',
    ticket_id       INTEGER REFERENCES repair_tickets(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE maintenance_events IS 'Individual maintenance event instances generated from schedules. Tracks completion and can link to repair tickets.';
CREATE INDEX idx_maint_events_due ON maintenance_events(due_date);
CREATE INDEX idx_maint_events_status ON maintenance_events(status);


/* =====================================================================
 * Equipment Use Schedules
 * =====================================================================
 * Members can book time on schedulable equipment. Double-booking
 * prevention is handled at the application layer.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS equipment_schedules (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    equipment_id    INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    member_id       INTEGER NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    title           TEXT,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE equipment_schedules IS 'Equipment time-slot bookings by members. Double-booking prevention is enforced at the application layer.';
CREATE INDEX idx_equip_schedules_equipment ON equipment_schedules(equipment_id);
CREATE INDEX idx_equip_schedules_time ON equipment_schedules(start_time, end_time);


/* =====================================================================
 * Authorization Sessions & Enrollments
 * =====================================================================
 * Authorizer-led training sessions for equipment use approval.
 * equipment_ids is an integer array of equipment IDs covered by
 * the session. Members enroll via the enrollments table.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS equip_auth_sessions (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    equipment_ids   INTEGER[] DEFAULT '{}',
    authorizer_id   INTEGER NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ NOT NULL,
    total_slots     INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE equip_auth_sessions IS 'Authorizer-led equipment training/authorization sessions with enrollment slots.';
CREATE INDEX idx_equip_auth_sessions_time ON equip_auth_sessions(start_time);

CREATE TABLE IF NOT EXISTS equip_auth_enrollments (
    id              INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    session_id      INTEGER NOT NULL REFERENCES equip_auth_sessions(id) ON DELETE CASCADE,
    member_id       INTEGER NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    enrolled_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(session_id, member_id)
);
COMMENT ON TABLE equip_auth_enrollments IS 'Member enrollments in equipment authorization sessions. Unique constraint prevents double enrollment.';


/* =====================================================================
 * Equipment Module Configuration
 * =====================================================================
 * Key-value store for equipment module settings: dashboard tiles,
 * field templates, module toggles, notification config, etc.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS equipment_config (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_by  INTEGER REFERENCES member(id)
);
COMMENT ON TABLE equipment_config IS 'Key-value configuration store for the equipment module (dashboard, templates, notifications, etc.).';


/* =====================================================================
 * Auto-Update Triggers
 * =====================================================================
 * Automatically bumps updated_at and increments version on UPDATE
 * for tables that support optimistic locking.
 * ===================================================================== */

CREATE OR REPLACE FUNCTION equip_update_version()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    NEW.version = OLD.version + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_equipment_ver BEFORE UPDATE ON equipment
    FOR EACH ROW EXECUTE FUNCTION equip_update_version();
CREATE TRIGGER trg_tickets_ver BEFORE UPDATE ON repair_tickets
    FOR EACH ROW EXECUTE FUNCTION equip_update_version();


/* =====================================================================
 * OAuth2 Client for Equipment Portal
 * =====================================================================
 * IMPORTANT: Replace the placeholder secret before deployment!
 * Generate a real secret with: tools/generate_secret.sh
 * ===================================================================== */

INSERT INTO oauth2_users (client_name, client_secret, client_description)
VALUES (
    'dev-equipment-portal',
    '$2b$12$qHfcyqUpH2oYE.0UbChDiePnA3C0s75L3mTWzcZoxTzP6tvBUTlOK',
    'Equipment management portal application'
);

/* OAuth2 client for the Discord Bot (optional) */
INSERT INTO oauth2_users (client_name, client_secret, client_description)
VALUES (
    'dev-discord-bot',
    '$2b$12$qHfcyqUpH2oYE.0UbChDiePnA3C0s75L3mTWzcZoxTzP6tvBUTlOK',
    'Discord bot for equipment ticket management'
);


/* =====================================================================
 * Equipment Audit Log
 * =====================================================================
 * Separate audit log for equipment module tables. The trigger function
 * is SECURITY DEFINER so the application role cannot write to the
 * audit log directly — only the trigger can. Session context is set
 * per-request by the application using set_config().
 *
 * This may be merged with a global audit log in the future once RLS
 * is implemented across all Deep Harbor tables.
 * ===================================================================== */

CREATE TABLE IF NOT EXISTS equipment_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    table_name      TEXT NOT NULL,
    record_id       TEXT,
    operation       TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE')),
    user_id         TEXT,
    user_role       TEXT,
    old_data        JSONB,
    new_data        JSONB,
    changed_fields  TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE equipment_audit_log IS 'Audit trail for all equipment module data changes. Written by SECURITY DEFINER trigger only.';
CREATE INDEX idx_equip_audit_table ON equipment_audit_log(table_name);
CREATE INDEX idx_equip_audit_record ON equipment_audit_log(record_id);
CREATE INDEX idx_equip_audit_time ON equipment_audit_log(created_at);

-- Audit trigger function (SECURITY DEFINER — app role cannot bypass)
CREATE OR REPLACE FUNCTION equip_audit_trigger_fn()
RETURNS TRIGGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    _user_id   TEXT;
    _role      TEXT;
    _record_id TEXT;
    _old       JSONB;
    _new       JSONB;
    _changed   TEXT[];
BEGIN
    -- Read session context (set by the application per-request via set_config)
    _user_id := current_setting('app.current_user_id', true);
    _role    := current_setting('app.session_role', true);

    IF TG_OP = 'DELETE' THEN
        _old := to_jsonb(OLD);
        _record_id := COALESCE(_old->>'id', '');
        INSERT INTO equipment_audit_log (table_name, record_id, operation, user_id, user_role, old_data)
        VALUES (TG_TABLE_NAME, _record_id, 'DELETE', _user_id, _role, _old);
        RETURN OLD;

    ELSIF TG_OP = 'INSERT' THEN
        _new := to_jsonb(NEW);
        _record_id := COALESCE(_new->>'id', '');
        INSERT INTO equipment_audit_log (table_name, record_id, operation, user_id, user_role, new_data)
        VALUES (TG_TABLE_NAME, _record_id, 'INSERT', _user_id, _role, _new);
        RETURN NEW;

    ELSIF TG_OP = 'UPDATE' THEN
        _old := to_jsonb(OLD);
        _new := to_jsonb(NEW);
        _record_id := COALESCE(_new->>'id', '');
        -- Detect which fields changed
        _changed := ARRAY(
            SELECT key FROM jsonb_each(_new)
            WHERE NOT (_old ? key AND _old->key = _new->key)
        );
        -- Skip audit if nothing actually changed
        IF array_length(_changed, 1) IS NULL THEN RETURN NEW; END IF;
        INSERT INTO equipment_audit_log (table_name, record_id, operation, user_id, user_role, old_data, new_data, changed_fields)
        VALUES (TG_TABLE_NAME, _record_id, 'UPDATE', _user_id, _role, _old, _new, _changed);
        RETURN NEW;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Attach audit triggers to all equipment module tables
CREATE TRIGGER audit_areas               AFTER INSERT OR UPDATE OR DELETE ON areas                FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_equipment           AFTER INSERT OR UPDATE OR DELETE ON equipment            FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_equipment_groups    AFTER INSERT OR UPDATE OR DELETE ON equipment_groups     FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_repair_tickets      AFTER INSERT OR UPDATE OR DELETE ON repair_tickets       FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_maint_schedules     AFTER INSERT OR UPDATE OR DELETE ON maintenance_schedules FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_maint_events        AFTER INSERT OR UPDATE OR DELETE ON maintenance_events   FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_equip_schedules     AFTER INSERT OR UPDATE OR DELETE ON equipment_schedules  FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_equip_auth_sessions AFTER INSERT OR UPDATE OR DELETE ON equip_auth_sessions  FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_equip_auth_enroll   AFTER INSERT OR UPDATE OR DELETE ON equip_auth_enrollments FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();
CREATE TRIGGER audit_equip_config        AFTER INSERT OR UPDATE OR DELETE ON equipment_config     FOR EACH ROW EXECUTE FUNCTION equip_audit_trigger_fn();


/* =====================================================================
 * Least-Privilege Application Role (dh_app)
 * =====================================================================
 * This role is used by the DHEquipment service for all database access.
 * It has DML access to data tables but cannot modify schema, truncate
 * tables, or write directly to the audit log.
 *
 * The password is a placeholder — set via environment variable in the
 * init-roles script or docker-compose before deployment.
 *
 * Existing DH services continue using the 'dh' superuser until they
 * are individually migrated to dh_app in a later sprint.
 * ===================================================================== */

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dh_app') THEN
        CREATE ROLE dh_app LOGIN PASSWORD 'changeme_in_env';
    END IF;
END $$;

-- Existing DH tables: full DML
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    member, member_audit, oauth2_users,
    roles, member_to_role, user_activity_logs,
    rfid_board_sync, waivers, subscriptions, products,
    email_templates, email_template_parameters,
    service_endpoints, membership_types_lookup,
    available_authorizations, member_changes,
    member_changes_processing_log, member_access_log
TO dh_app;

-- Equipment module tables: full DML
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    areas, equipment, equipment_groups, equipment_group_members,
    repair_tickets, maintenance_schedules, maintenance_events,
    equipment_schedules, equip_auth_sessions, equip_auth_enrollments,
    equipment_config
TO dh_app;

-- Audit log: read-only (writes happen via SECURITY DEFINER trigger)
GRANT SELECT ON equipment_audit_log TO dh_app;

-- Sequences
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dh_app;


/* =====================================================================
 * Row Level Security — Equipment Module
 * =====================================================================
 * Starting permissive: open reads, open writes for dh_app.
 * The equipment_config table is gated by session role — only
 * Administrator, SuperAdmin, and Area Host can modify it.
 *
 * These policies will be tightened in a future sprint.
 * ===================================================================== */

-- Equipment config: role-gated writes
ALTER TABLE equipment_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE equipment_config FORCE ROW LEVEL SECURITY;

CREATE POLICY equip_config_select ON equipment_config
    FOR SELECT USING (true);

CREATE POLICY equip_config_insert ON equipment_config
    FOR INSERT WITH CHECK (
        current_setting('app.session_role', true) IN ('Administrator', 'SuperAdmin', 'Area Host')
        OR COALESCE(current_setting('app.session_role', true), '') = ''
    );

CREATE POLICY equip_config_update ON equipment_config
    FOR UPDATE USING (
        current_setting('app.session_role', true) IN ('Administrator', 'SuperAdmin', 'Area Host')
        OR COALESCE(current_setting('app.session_role', true), '') = ''
    );

-- All other equipment tables: permissive (tighten later)
ALTER TABLE areas ENABLE ROW LEVEL SECURITY;
CREATE POLICY areas_all ON areas FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE equipment ENABLE ROW LEVEL SECURITY;
CREATE POLICY equipment_all ON equipment FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE equipment_groups ENABLE ROW LEVEL SECURITY;
CREATE POLICY equip_groups_all ON equipment_groups FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE equipment_group_members ENABLE ROW LEVEL SECURITY;
CREATE POLICY equip_group_members_all ON equipment_group_members FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE repair_tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY repair_tickets_all ON repair_tickets FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE maintenance_schedules ENABLE ROW LEVEL SECURITY;
CREATE POLICY maint_schedules_all ON maintenance_schedules FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE maintenance_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY maint_events_all ON maintenance_events FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE equipment_schedules ENABLE ROW LEVEL SECURITY;
CREATE POLICY equip_schedules_all ON equipment_schedules FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE equip_auth_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY equip_auth_sessions_all ON equip_auth_sessions FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE equip_auth_enrollments ENABLE ROW LEVEL SECURITY;
CREATE POLICY equip_auth_enroll_all ON equip_auth_enrollments FOR ALL USING (true) WITH CHECK (true);
