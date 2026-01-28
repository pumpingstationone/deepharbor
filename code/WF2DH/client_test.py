import os
import json
import requests


from config import config
from dhs_logging import logger

###############################################################################
# WaiverForever API Configuration
###############################################################################
WF_API_KEY = config['WaiverForever']['api_key']
WF_BASE_URL = config['WaiverForever']['base_url']

headers = {
    "X-API-Key": WF_API_KEY,
    "Accept": "application/json"
}


###############################################################################
# Main function to interact with WaiverForever API
###############################################################################

def main():
    logger.info("Starting WF2DH test process")
    
    try:
        response = requests.get(f'{WF_BASE_URL}/openapi/v1/auth/userInfo', params={}, headers=headers)        
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        waivers_data = response.json()
        logger.info(json.dumps(waivers_data, indent=4))
        
        # Get the webhook subscriptions
        response = requests.get(f'{WF_BASE_URL}/openapi/v1/webhooks/', params={}, headers=headers)
        response.raise_for_status()
        webhooks_data = response.json()
        logger.info(json.dumps(webhooks_data, indent=4))

    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
