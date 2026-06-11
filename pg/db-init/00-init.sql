/* The pgcrypto extension is used for generating secure random tokens and hashing sensitive data like passwords. */
CREATE EXTENSION IF NOT EXISTS pgcrypto;
/* 
 * The timescaledb extension is used for efficient storage and querying of time-series data, 
 * which is relevant for tracking member access logs and other time-based events. 
 */
CREATE EXTENSION IF NOT EXISTS timescaledb;
/* pg_trgm provides trigram-based fuzzy/substring matching used by the admin-portal
 * member search (search_members_by_identity_and_access). */
CREATE EXTENSION IF NOT EXISTS pg_trgm;
/* unaccent provides accent-folding (e.g. José -> Jose) for member search. */
CREATE EXTENSION IF NOT EXISTS unaccent;

/* Schema is created in the pgsql_schema.sql file */