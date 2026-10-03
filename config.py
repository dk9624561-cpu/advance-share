import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# Helper function to safely parse integer channel IDs
def parse_channel_id(value):
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value

SOURCE_CHANNEL_ID = parse_channel_id(os.getenv("SOURCE_CHANNEL_ID"))
DESTINATION_CHANNEL_ID = parse_channel_id(os.getenv("DESTINATION_CHANNEL_ID"))
ADMIN_USER_ID = parse_channel_id(os.getenv("ADMIN_USER_ID"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db")
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "5"))


# Simple validation
def validate_config():
    global BOT_USERNAME
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is missing in environment variables.")
    
    # Strip '@' from username if the user accidentally included it
    if BOT_USERNAME and BOT_USERNAME.startswith('@'):
        BOT_USERNAME = BOT_USERNAME[1:]
        
    return errors
