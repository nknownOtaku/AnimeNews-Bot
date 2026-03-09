import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

MONGO_URI = os.getenv("MONGO_URI")

URL_A = os.getenv("URL_A")

START_PIC = os.getenv("START_PIC")

ADMINS = [int(x) for x in os.getenv("ADMINS", "").split()]
