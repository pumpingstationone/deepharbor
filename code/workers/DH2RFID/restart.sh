#!/usr/bin/env bash

# Get the current directory name and convert to lowercase
SERVICE=$(basename "$PWD" | tr '[:upper:]' '[:lower:]')

# Rebuild the Docker image
echo "Rebuilding image for service: $SERVICE"
docker compose build "$SERVICE"

if [ $? -ne 0 ]; then
    echo "Failed to build image for service: $SERVICE"
    exit 1
fi

# Execute docker compose with the service name
docker compose up -d --no-deps --force-recreate "$SERVICE"

# Check if the command was successful
if [ $? -eq 0 ]; then
    echo "Successfully rebuilt and recreated service: $SERVICE"
else
    echo "Failed to recreate service: $SERVICE"
    exit 1
fi
