import configparser
import os

###############################################################################
# Configuration
###############################################################################

config = configparser.ConfigParser()
config.read("config.ini")

# Also read the git version file generated during Docker build
config.read("git_version.ini")

### Environment variable overrides
# DHService (member management)
if os.environ.get("DH_API_BASE_URL"):
    if not config.has_section("dh_services"):
        config.add_section("dh_services")
    config.set("dh_services", "api_base_url", os.environ["DH_API_BASE_URL"])

if os.environ.get("DH_CLIENT_ID"):
    if not config.has_section("dh_services"):
        config.add_section("dh_services")
    config.set("dh_services", "client_name", os.environ["DH_CLIENT_ID"])

if os.environ.get("DH_CLIENT_SECRET"):
    if not config.has_section("dh_services"):
        config.add_section("dh_services")
    config.set("dh_services", "client_secret", os.environ["DH_CLIENT_SECRET"])

# DHEquipment service
if os.environ.get("DH_EQUIP_API_BASE_URL"):
    if not config.has_section("dh_equipment"):
        config.add_section("dh_equipment")
    config.set("dh_equipment", "api_base_url", os.environ["DH_EQUIP_API_BASE_URL"])

if os.environ.get("DH_EQUIP_CLIENT_ID"):
    if not config.has_section("dh_equipment"):
        config.add_section("dh_equipment")
    config.set("dh_equipment", "client_name", os.environ["DH_EQUIP_CLIENT_ID"])

if os.environ.get("DH_EQUIP_CLIENT_SECRET"):
    if not config.has_section("dh_equipment"):
        config.add_section("dh_equipment")
    config.set("dh_equipment", "client_secret", os.environ["DH_EQUIP_CLIENT_SECRET"])

# DHAdminPortal base URL (for Settings redirect link)
if os.environ.get("DH_ADMIN_BASE_URL"):
    if not config.has_section("dh_admin"):
        config.add_section("dh_admin")
    config.set("dh_admin", "base_url", os.environ["DH_ADMIN_BASE_URL"])

# Flask secret key
if os.environ.get("DH_SECRET_KEY"):
    if not config.has_section("flask"):
        config.add_section("flask")
    config.set("flask", "secret_key", os.environ["DH_SECRET_KEY"])
