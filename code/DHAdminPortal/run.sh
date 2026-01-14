#!/usr/bin/env bash

# From https://learn.microsoft.com/en-us/azure/active-directory-b2c/enable-authentication-python-web-app?tabs=macos

# Complaint from flask that this is the new way to
# enable debugging
export FLASK_DEBUG=true
export FLASK_APP=app.py

echo "Starting Flask app... $FLASK_APP"
uv run -- flask run --host=0.0.0.0  -p 5001

