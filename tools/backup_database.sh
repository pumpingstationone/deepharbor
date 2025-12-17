#!/usr/bin/env bash

# This is a simple script to back up the DeepHarbor PostgreSQL database to a SQL file.
# It assumes that pg_dump is installed and that the database is accessible.
# on localhost with the username and password set below.

export PGUSER=dh
export PGPASSWORD=dh
pg_dump -h localhost -d deepharbor -f dh.sql
# Unset variables for security
unset PGPASSWORD

