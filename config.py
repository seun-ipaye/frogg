import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DATABASE_PATH = os.environ.get("DATABASE_PATH", "frogg.db")
