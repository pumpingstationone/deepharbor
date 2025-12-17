# `code`
This directory contains all the source code for the Deep Harbor system, excluding some scripts and the database schema files, which are located in the `../pg` directory.

## Required tools
To build and run the Deep Harbor system, you will need the following tools installed on your machine:
- [Python 3.14+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/)

## Passwords and Secrets
Note that to to make it easier to set up the Deep Harbor system, some passwords and secrets are hardcoded in the source code. These should be changed before deploying the system in a production environment. Suffice to say, these are not used in production deployments. 😇

## `config.ini` files
Several components of the Deep Harbor system use `config.ini` files for configuration. These files are included in the source code with default settings. You may need to modify these files to suit your deployment. These are used for allowing the system to be used in a non-Docker environment, or for development purposes. In production deployments using Docker, these files are typically overridden by environment variables set in the Docker Compose files.