import os

# config.py requires this at import time; the tests never connect to Discord.
os.environ.setdefault("DISCORD_TOKEN", "test-token")
