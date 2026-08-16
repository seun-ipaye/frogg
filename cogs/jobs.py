import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

from db import (
    get_priority_province,
    get_unposted_job_ids,
    is_channel_registered,
    list_channels,
    mark_posted,
    register_channel,
    unregister_channel,
)
from pipeline import run_pipeline
from province import PROVINCES, detect_province, province_name
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


def build_job_embeds(jobs: list[Job], section_title: str | None = None) -> list[discord.Embed]:
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
        title = section_title or "New Canadian Co-op/Internship Postings"
        embeds[0].title = f"{title} ({len(jobs)})"
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


NO_PREFERENCE = "ALL"  # dropdown option value for "All of Canada" - SelectOption.value can't be empty


class ProvinceSelect(discord.ui.Select):
    def __init__(self, guild_id: int, guild_name: str | None):
        self.guild_id = guild_id
        self.guild_name = guild_name
        options = [discord.SelectOption(label="All of Canada (no preference)", value=NO_PREFERENCE)] + [
            discord.SelectOption(label=f"{name} ({code})", value=code) for name, code in PROVINCES
        ]
        super().__init__(placeholder="Choose a priority province...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        province = None if self.values[0] == NO_PREFERENCE else self.values[0]
        register_channel(interaction.channel_id, self.guild_id, self.guild_name, priority_province=province)
        label = province_name(province) if province else "All of Canada (no preference)"
        await interaction.response.edit_message(
            content=(
                f"This channel is registered for Frogg postings "
                f"(automatically at 12am/6am/12pm/6pm ET). Priority location: **{label}**. "
                "Run `!jobs` anytime to check manually."
            ),
            view=None,
        )
        # Without this, the view's timeout task is still armed - it fires
        # on_timeout() ~120s later and edits this same message again,
        # clobbering the confirmation above with a stale "timed out" text
        # even though registration already succeeded.
        self.view.stop()


class ProvinceSelectView(discord.ui.View):
    def __init__(self, guild_id: int, guild_name: str | None):
        super().__init__(timeout=120)
        self.message: discord.Message | None = None
        self.add_item(ProvinceSelect(guild_id, guild_name))

    async def on_timeout(self):
        if self.message:
            await self.message.edit(content="Setup timed out - run `!setup` again to register this channel.", view=None)


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

    async def _post_to_channel(
        self, channel: discord.abc.Messageable, matched_jobs: list[Job], priority_province: str | None
    ) -> list[Job]:
        """Post whichever of the given jobs this specific channel hasn't
        seen yet, then record them as posted for this channel. If the
        channel has a priority province, split the post into an
        in-province section and a rest-of-Canada section."""
        unposted_ids = get_unposted_job_ids(channel.id, [job.id for job in matched_jobs])
        to_post = [job for job in matched_jobs if job.id in unposted_ids]

        if priority_province:
            in_province_ids = {job.id for job in to_post if detect_province(job.location) == priority_province}
            sections = [
                (f"📍 Jobs in {province_name(priority_province)}", [job for job in to_post if job.id in in_province_ids]),
                ("🍁 Rest of Canada", [job for job in to_post if job.id not in in_province_ids]),
            ]
        else:
            sections = [(None, to_post)]

        for title, jobs in sections:
            if not jobs:
                continue
            embeds = build_job_embeds(jobs, section_title=title)
            for batch in batch_embeds_by_message(embeds):
                await channel.send(embeds=batch)

        for job in to_post:
            mark_posted(channel.id, job.id)

        return to_post

    async def scheduled_scrape(self):
        matched_jobs = await asyncio.to_thread(run_pipeline)
        for channel_id, priority_province in list_channels():
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                logger.warning("Registered channel %s not found/accessible, skipping", channel_id)
                continue
            try:
                posted = await self._post_to_channel(channel, matched_jobs, priority_province)
                logger.info("Posted %d new job(s) to channel %s", len(posted), channel_id)
            except Exception:
                # One channel failing (permissions revoked, a transient
                # Discord API error, etc.) shouldn't stop every other
                # registered channel from getting posted to.
                logger.exception("Failed to post to channel %s, skipping", channel_id)

    @commands.command(name="jobs")
    async def jobs(self, ctx: commands.Context):
        if not is_channel_registered(ctx.channel.id):
            await ctx.send(
                'This channel isn\'t set up yet. Ask someone with "Manage Server" '
                "permission to run `!setup` here first."
            )
            return

        await ctx.send("Scraping for new postings...")
        matched_jobs = await asyncio.to_thread(run_pipeline)
        priority_province = get_priority_province(ctx.channel.id)
        posted = await self._post_to_channel(ctx.channel, matched_jobs, priority_province)

        if not posted:
            await ctx.send("No new Canadian co-op/internship postings found.")

    @commands.command(name="status")
    async def status(self, ctx: commands.Context):
        if not is_channel_registered(ctx.channel.id):
            await ctx.send("This channel isn't registered. Run `!setup` to register it.")
            return

        priority_province = get_priority_province(ctx.channel.id)
        label = province_name(priority_province) if priority_province else "All of Canada (no preference)"
        await ctx.send(
            "This channel is registered for Frogg postings "
            "(automatically at 12am/6am/12pm/6pm ET).\n"
            f"Priority location: **{label}**."
        )

    @commands.command(name="setup")
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_channel(self, ctx: commands.Context):
        view = ProvinceSelectView(ctx.guild.id, ctx.guild.name)
        view.message = await ctx.send(
            "Pick a priority province for this channel — postings from it will be "
            "shown separately from the rest of Canada. Choose \"All of Canada\" for "
            "one combined list instead:",
            view=view,
        )

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
