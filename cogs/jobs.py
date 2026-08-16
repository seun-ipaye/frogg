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

# Discord hard limits: 25 fields per embed, 10 embeds per message, and (the
# one that actually bites here) 6000 total characters summed across every
# embed in a single message. Job titles/locations vary a lot in length
# (some locations are 4-5 cities joined together), so a fixed field/embed
# count isn't safe - batching has to account for actual content size.
JOBS_PER_EMBED = 8
EMBEDS_PER_MESSAGE = 10
MAX_MESSAGE_CHARS = 5500  # stay under Discord's 6000 with a safety margin


def _embed_char_count(embed: discord.Embed) -> int:
    count = len(embed.title or "") + len(embed.description or "")
    if embed.footer and embed.footer.text:
        count += len(embed.footer.text)
    for field in embed.fields:
        count += len(field.name) + len(field.value)
    return count


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
                value=(f"📍 {job.location or 'Not specified'} • [Apply]({job.url})")[:1024],
                inline=False,
            )
        embeds.append(embed)

    if embeds:
        embeds[0].title = f"New Canadian Co-op/Internship Postings ({len(jobs)})"
        embeds[-1].set_footer(text="Frogg 🐸")
        embeds[-1].timestamp = discord.utils.utcnow()

    return embeds


def batch_embeds_by_message(embeds: list[discord.Embed]) -> list[list[discord.Embed]]:
    """Group embeds into per-message batches that respect Discord's 10
    embeds/message cap and stay under the 6000-char combined size limit."""
    batches: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    current_chars = 0

    for embed in embeds:
        chars = _embed_char_count(embed)
        would_overflow = current and (
            len(current) >= EMBEDS_PER_MESSAGE or current_chars + chars > MAX_MESSAGE_CHARS
        )
        if would_overflow:
            batches.append(current)
            current, current_chars = [], 0
        current.append(embed)
        current_chars += chars

    if current:
        batches.append(current)

    return batches


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
        for batch in batch_embeds_by_message(embeds):
            await channel.send(embeds=batch)
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
