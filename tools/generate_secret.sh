#!/usr/bin/env bash

# Requires 'bcrypt' module for Python
# Install with: pip install bcrypt
python3 -c "import bcrypt; import secrets; secret = secrets.token_urlsafe(32); hashed = bcrypt.hashpw(secret.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'); print(f'Plaintext secret (give to client): \t{secret}'); print(f'Hashed secret (store in db): \t\t{hashed}')"
