#!/usr/bin/env bash

# Note, requires passlib!
python3 -c "from passlib.context import CryptContext; import secrets; pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto'); secret = secrets.token_urlsafe(32); print(f'Plaintext secret (give to client): \t{secret}'); print(f'Hashed secret (store in db): \t\t{pwd_context.hash(secret)}')"
