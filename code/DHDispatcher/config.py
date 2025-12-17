import configparser
import os

###############################################################################
# Configuration
###############################################################################

# create a new configuration parser
config = configparser.ConfigParser()
config.read("config.ini")

# Override with environment variables if running in Docker
if os.getenv("DATABASE_HOST"):
    config["Database"]["host"] = os.getenv("DATABASE_HOST")
if os.getenv("DATABASE_PORT"):
    config["Database"]["port"] = os.getenv("DATABASE_PORT")
if os.getenv("DATABASE_NAME"):
    config["Database"]["name"] = os.getenv("DATABASE_NAME")
if os.getenv("DATABASE_USER"):
    config["Database"]["user"] = os.getenv("DATABASE_USER")
if os.getenv("DATABASE_PASSWORD"):
    config["Database"]["password"] = os.getenv("DATABASE_PASSWORD")
