#!/usr/bin/env bash

# Shuts down the DeepHarbor environment
docker compose down --volumes

# Remove the Docker network
docker network rm dh_network