import requests
import os
import json

from fastapi import Depends

# Our fastapi app
from fastapiapp import app

import psycopg2

from config import config
from dhs_logging import logger

###############################################################################
# Healthcheck endpoint
###############################################################################

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": os.getenv("SERVICE_NAME", "WF2DH_SERVICE")}


###############################################################################
# Wehbhook endpoint to receive WaiverForever events
###############################################################################

@app.post("/receiveWillNotDieHereWaiver")
async def waiver_webhook(payload: dict):
    logger.info("Received a new waiver from WaiverForever:")
    logger.info(json.dumps(payload, indent=4))
    
    # Now we want to process the payload and store it in the database
    try:
        conn = psycopg2.connect(
            dbname=config['Database']['name'],
            user=config['Database']['user'],
            password=config['Database']['password'],
            host=config['Database']['host'],
            port=config['Database']['port']
        )
        cursor = conn.cursor()
        
        insert_query = """
            INSERT INTO waivers (details)
            VALUES (%s)
        """
        details = json.dumps(payload)
        cursor.execute(insert_query, (details,))
        conn.commit()        
        
        cursor.close()
        conn.close()
        
        logger.info(f"Waiver stored successfully.")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error storing waiver: {e}")
        return {"status": "error", "message": str(e)}
