#!/usr/bin/env bash

# If you've added a service to the gateway (i.e. nginx) - use this script to
# rebuild and redeploy to prevent spending an excessive amount of time trying
# to diagnose why your service is not working :eyeroll:
docker compose build gateway; docker compose up -d --no-deps --force-recreate gateway
