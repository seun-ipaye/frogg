import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DATABASE_PATH = os.environ.get("DATABASE_PATH", "frogg.db")
TOPGG_TOKEN = os.environ.get("TOPGG_TOKEN")  # optional - top.gg stats posting is skipped without it


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name) or default))
    except ValueError:
        return default


# Public listings repo sync. All optional: the sync stays off unless either
# LISTINGS_OUTPUT_DIR (local preview) or GITHUB_TOKEN + GITHUB_REPO is set.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or None
GITHUB_REPO = os.environ.get("GITHUB_REPO") or None  # "owner/name" of the PUBLIC listings repo, not the bot repo
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH") or "main"
LISTINGS_OUTPUT_DIR = os.environ.get("LISTINGS_OUTPUT_DIR") or None  # write files here instead of pushing
LISTINGS_SYNC_INTERVAL_MINUTES = _int_env("LISTINGS_SYNC_INTERVAL_MINUTES", 30)
BOT_INVITE_URL = os.environ.get("BOT_INVITE_URL") or None
# Credit line in the listings README ("Built and maintained by ..."). Edit these
# (or the env vars), not the generated README - the bot overwrites that file.
CREATOR_NAME = os.environ.get("CREATOR_NAME") or "Seun Samuel-Ipaye"
CREATOR_LINKEDIN_URL = os.environ.get("CREATOR_LINKEDIN_URL") or "https://www.linkedin.com/in/seunipaye/"
CREATOR_GITHUB_URL = os.environ.get("CREATOR_GITHUB_URL") or None  # opt-in; not shown by default

# SimplifyJobs renames this repo each year (Summer2026 -> Summer2027); GitHub
# redirects the old name, but don't depend on that.
COOP_TRACKER_REPO = os.environ.get("COOP_TRACKER_REPO") or "Summer2027-Internships"
