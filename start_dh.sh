#!/usr/bin/env bash

# This script sets up and starts DeepHarbor, including the PostgreSQL database.
# It assumes Docker and Docker Compose are installed on the system.

# Create a Docker network for DeepHarbor
docker network create dh_network

# Now start the services using Docker Compose
docker compose up -d