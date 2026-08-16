import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

from config import DISCORD_CHANNEL_ID
from pipeline import run_pipeline
from scrapers.base import Job

SCRAPE_INTERVAL_HOURS = 6

# Discord hard limits: 25 fields per embed, 10 embeds per message. Keeping
# well under the field limit so postings stay readable rather than cramped.
JOBS_PER_EMBED = 10
EMBEDS_PER_MESSAGE = 10

logger = logging.getLogger(__name__)


def build_job_embeds(jobs: list[Job]) -> list[discord.Embed]:
    """Pack jobs into embeds (JOBS_PER_EMBED fields each) so a large batch
    posts as a handful of messages instead of one message per job."""
    embeds = []
    for i in range(0, len(jobs), JOBS_PER_EMBED):
        chunk = jobs[i : i + JOBS_PER_EMBED]
        embed = discord.Embed(color=discord.Color.blurple())
        for job in chunk:
            embed.add_field(
                name=f"{job.title} — {job.company}"[:256],
                value=f"📍 {job.location or 'Not specified'} • [Apply]({job.url})",
                inline=False,
            )
        embeds.append(embed)

    if embeds:
        embeds[0].title = f"New Canadian Co-op/Internship Postings ({len(jobs)})"
        embeds[-1].set_footer(text="Frogg 🐸")
        embeds[-1].timestamp = discord.utils.utcnow()

    return embeds


class JobsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()

    async def cog_load(self):
        self.scheduler.add_job(
            self.scheduled_scrape,
            trigger=IntervalTrigger(hours=SCRAPE_INTERVAL_HOURS),
            id="scrape_jobs",
        )
        self.scheduler.start()

    async def cog_unload(self):
        self.scheduler.shutdown(wait=False)

    async def post_new_jobs(self, channel: discord.abc.Messageable) -> list[Job]:
        new_jobs = await asyncio.to_thread(run_pipeline)
        embeds = build_job_embeds(new_jobs)
        for i in range(0, len(embeds), EMBEDS_PER_MESSAGE):
            await channel.send(embeds=embeds[i : i + EMBEDS_PER_MESSAGE])
        return new_jobs

    async def scheduled_scrape(self):
        channel = self.bot.get_channel(DISCORD_CHANNEL_ID)
        if channel is None:
            logger.warning("Scheduled scrape skipped: channel %s not found", DISCORD_CHANNEL_ID)
            return
        new_jobs = await self.post_new_jobs(channel)
        logger.info("Scheduled scrape posted %d new job(s)", len(new_jobs))

    @commands.command(name="jobs")
    async def jobs(self, ctx: commands.Context):
        await ctx.send("Scraping for new postings...")
        channel = self.bot.get_channel(DISCORD_CHANNEL_ID) or ctx.channel
        new_jobs = await self.post_new_jobs(channel)

        if not new_jobs:
            await ctx.send("No new Canadian co-op/internship postings found.")


async def setup(bot: commands.Bot):
    await bot.add_cog(JobsCog(bot))
