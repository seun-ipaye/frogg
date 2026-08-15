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

logger = logging.getLogger(__name__)


def job_to_embed(job: Job) -> discord.Embed:
    embed = discord.Embed(title=job.title, url=job.url, color=discord.Color.blurple())
    embed.add_field(name="Company", value=job.company, inline=True)
    embed.add_field(name="Location", value=job.location or "Not specified", inline=True)
    embed.add_field(name="Type", value=job.job_type or "Internship/Co-op", inline=True)
    embed.set_footer(text=f"Source: {job.source}")
    return embed


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
        for job in new_jobs:
            await channel.send(embed=job_to_embed(job))
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
