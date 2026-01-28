import logging

# Set up the logging with the date and time of the log
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.DEBUG)
logger = logging.getLogger(__name__)
