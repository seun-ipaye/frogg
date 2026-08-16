import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

from db import get_unposted_job_ids, list_channel_ids, mark_posted, register_channel, unregister_channel
from pipeline import run_pipeline
from scrapers.base import Job

# Fixed posting times rather than "every 6 hours from process start" - the
# latter drifts on every restart/redeploy, so students would never know
# when to expect a post. Timezone is set explicitly since the container's
# system clock (Railway defaults to UTC) won't match Windsor, ON.
SCRAPE_HOURS = "0,6,12,18"
SCRAPE_TIMEZONE = "America/Toronto"

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
            trigger=CronTrigger(hour=SCRAPE_HOURS, minute=0, timezone=SCRAPE_TIMEZONE),
            id="scrape_jobs",
        )
        self.scheduler.start()

    async def cog_unload(self):
        self.scheduler.shutdown(wait=False)

    async def _post_to_channel(self, channel: discord.abc.Messageable, matched_jobs: list[Job]) -> list[Job]:
        """Post whichever of the given jobs this specific channel hasn't
        seen yet, then record them as posted for this channel."""
        unposted_ids = get_unposted_job_ids(channel.id, [job.id for job in matched_jobs])
        to_post = [job for job in matched_jobs if job.id in unposted_ids]

        embeds = build_job_embeds(to_post)
        for batch in batch_embeds_by_message(embeds):
            await channel.send(embeds=batch)

        for job in to_post:
            mark_posted(channel.id, job.id)

        return to_post

    async def scheduled_scrape(self):
        matched_jobs = await asyncio.to_thread(run_pipeline)
        for channel_id in list_channel_ids():
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                logger.warning("Registered channel %s not found/accessible, skipping", channel_id)
                continue
            posted = await self._post_to_channel(channel, matched_jobs)
            logger.info("Posted %d new job(s) to channel %s", len(posted), channel_id)

    @commands.command(name="jobs")
    async def jobs(self, ctx: commands.Context):
        await ctx.send("Scraping for new postings...")
        matched_jobs = await asyncio.to_thread(run_pipeline)
        posted = await self._post_to_channel(ctx.channel, matched_jobs)

        if not posted:
            await ctx.send("No new Canadian co-op/internship postings found.")

    @commands.command(name="setup")
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_channel(self, ctx: commands.Context):
        newly_registered = register_channel(ctx.channel.id, ctx.guild.id, ctx.guild.name)
        if newly_registered:
            await ctx.send(
                "This channel is now registered for Frogg postings "
                "(automatically at 12am/6am/12pm/6pm ET). Run `!jobs` anytime to check manually."
            )
        else:
            await ctx.send("This channel is already registered.")

    @commands.command(name="stop")
    @commands.has_guild_permissions(manage_guild=True)
    async def stop_channel(self, ctx: commands.Context):
        removed = unregister_channel(ctx.channel.id)
        if removed:
            await ctx.send("This channel is unregistered. No more automatic postings here.")
        else:
            await ctx.send("This channel wasn't registered.")

    @setup_channel.error
    @stop_channel.error
    async def channel_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You need the \"Manage Server\" permission to run this.")
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(JobsCog(bot))
