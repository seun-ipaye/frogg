import asyncio
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from config import LISTINGS_SYNC_INTERVAL_MINUTES
from listings.publishers import build_publisher
from listings.sync import run_sync

logger = logging.getLogger(__name__)


class ListingsSyncCog(commands.Cog):
    """Keeps the public listings repo current. Own scheduler, own error
    handling, and no shared state with JobsCog: a failure here is logged and
    retried next interval, and can never affect Discord posting."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self.publisher = None

    async def cog_load(self):
        try:
            self.publisher = build_publisher()
        except Exception:
            logger.exception("Listings sync disabled: couldn't set up the publisher")
            return
        if self.publisher is None:
            logger.info("Listings sync disabled (set GITHUB_TOKEN + GITHUB_REPO, or LISTINGS_OUTPUT_DIR)")
            return

        self.scheduler.add_job(
            self.sync,
            trigger=IntervalTrigger(minutes=LISTINGS_SYNC_INTERVAL_MINUTES),
            id="listings_sync",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=60),  # first run shortly after boot
        )
        self.scheduler.start()
        logger.info("Listings sync enabled (%s, every %d min)", type(self.publisher).__name__, LISTINGS_SYNC_INTERVAL_MINUTES)

    async def cog_unload(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def sync(self):
        try:
            summary = await asyncio.to_thread(run_sync, self.publisher)
            logger.info("Listings sync: %s", summary.describe())
        except Exception:
            logger.exception("Listings sync failed (Discord posting is unaffected); retrying next interval")


async def setup(bot: commands.Bot):
    await bot.add_cog(ListingsSyncCog(bot))
