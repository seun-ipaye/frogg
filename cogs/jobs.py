import asyncio
import logging

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

from db import (
    get_include_new_grad,
    get_priority_province,
    get_unposted_job_ids,
    is_channel_registered,
    list_channels,
    mark_posted,
    register_channel,
    set_new_grad_preference,
    unregister_channel,
)
from pipeline import is_new_grad, run_pipeline
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


GUILDS_PER_EMBED = 20  # Discord hard caps at 25 fields per embed; leave a margin


def build_guild_embeds(guilds: list[discord.Guild]) -> list[discord.Embed]:
    """Pack guilds into embeds (GUILDS_PER_EMBED fields each) - a single
    embed silently breaks once the bot passes 25 servers."""
    embeds = []
    for i in range(0, len(guilds), GUILDS_PER_EMBED):
        chunk = guilds[i : i + GUILDS_PER_EMBED]
        embed = discord.Embed(color=discord.Color.blurple())
        for guild in chunk:
            embed.add_field(name=guild.name, value=f"{guild.member_count} members", inline=False)
        embeds.append(embed)

    if embeds:
        total_members = sum(g.member_count or 0 for g in guilds)
        embeds[0].title = f"Frogg is in {len(guilds)} server(s)"
        embeds[0].description = f"Total members across all servers: {total_members}"

    return embeds


NO_PREFERENCE = "ALL"  # dropdown option value for "All of Canada" - SelectOption.value can't be empty
NEW_GRAD_ON = "on"
NEW_GRAD_OFF = "off"


def _setup_status_text(priority_province: str | None, include_new_grad: bool) -> str:
    location_label = province_name(priority_province) if priority_province else "All of Canada (no preference)"
    new_grad_label = "On" if include_new_grad else "Off"
    return (
        "Pick a priority province, and whether to include new grad roles. "
        "Postings run automatically at 12am/6am/12pm/6pm ET, or check manually with `!jobs`.\n\n"
        f"📍 Priority location: **{location_label}**\n"
        f"🎓 New grad roles: **{new_grad_label}**"
    )


def _mark_default(options: list[discord.SelectOption], selected_value: str) -> None:
    """Discord's Select widget shows only the placeholder text in its
    collapsed state unless one option is explicitly flagged as the
    current selection - without this, a choice looks unconfirmed even
    though it was saved correctly."""
    for option in options:
        option.default = option.value == selected_value


class ProvinceSelect(discord.ui.Select):
    def __init__(self, guild_id: int, guild_name: str | None, current_province: str | None):
        self.guild_id = guild_id
        self.guild_name = guild_name
        options = [discord.SelectOption(label="All of Canada (no preference)", value=NO_PREFERENCE)] + [
            discord.SelectOption(label=f"{name} ({code})", value=code) for name, code in PROVINCES
        ]
        _mark_default(options, current_province or NO_PREFERENCE)
        super().__init__(placeholder="Choose a priority province...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        _mark_default(self.options, selected_value)
        province = None if selected_value == NO_PREFERENCE else selected_value
        register_channel(interaction.channel_id, self.guild_id, self.guild_name, priority_province=province)
        include_new_grad = get_include_new_grad(interaction.channel_id)
        await interaction.response.edit_message(
            content=_setup_status_text(province, include_new_grad), view=self.view
        )


class NewGradSelect(discord.ui.Select):
    def __init__(self, guild_id: int, guild_name: str | None, current_include_new_grad: bool):
        self.guild_id = guild_id
        self.guild_name = guild_name
        options = [
            discord.SelectOption(label="New grad roles: Off (co-ops/internships only)", value=NEW_GRAD_OFF),
            discord.SelectOption(label="New grad roles: On (include full-time new grad postings)", value=NEW_GRAD_ON),
        ]
        _mark_default(options, NEW_GRAD_ON if current_include_new_grad else NEW_GRAD_OFF)
        super().__init__(placeholder="Include new grad roles?", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        _mark_default(self.options, selected_value)
        include_new_grad = selected_value == NEW_GRAD_ON
        set_new_grad_preference(interaction.channel_id, self.guild_id, self.guild_name, include_new_grad)
        priority_province = get_priority_province(interaction.channel_id)
        await interaction.response.edit_message(
            content=_setup_status_text(priority_province, include_new_grad), view=self.view
        )


class SetupView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        guild_name: str | None,
        current_province: str | None,
        current_include_new_grad: bool,
    ):
        super().__init__(timeout=120)
        self.message: discord.Message | None = None
        self.add_item(ProvinceSelect(guild_id, guild_name, current_province))
        self.add_item(NewGradSelect(guild_id, guild_name, current_include_new_grad))

    async def on_timeout(self):
        # Disable the dropdowns rather than overwriting the message - with
        # two independent selects, one firing shouldn't kill the other's
        # ability to respond, and the last-shown settings are still
        # accurate and worth leaving visible rather than replacing with
        # "timed out" text.
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.NotFound:
            pass  # message was deleted in the meantime


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
        self,
        channel: discord.abc.Messageable,
        matched_jobs: list[Job],
        priority_province: str | None,
        include_new_grad: bool,
    ) -> list[Job]:
        """Post whichever of the given jobs this specific channel hasn't
        seen yet, then record them as posted for this channel. Splits into
        up to 4 sections: co-op/new-grad x in-province/rest-of-Canada,
        depending on this channel's settings. New grad jobs are only ever
        included (and only ever marked posted) if include_new_grad is on -
        otherwise they stay eligible for later, in case the channel opts
        in before they age out of the recency window."""
        unposted_ids = get_unposted_job_ids(channel.id, [job.id for job in matched_jobs])
        to_post = [job for job in matched_jobs if job.id in unposted_ids]

        coop_jobs = [job for job in to_post if not is_new_grad(job)]
        new_grad_jobs = [job for job in to_post if is_new_grad(job)] if include_new_grad else []

        if priority_province:
            province_label = province_name(priority_province)
            in_province = lambda jobs: [j for j in jobs if detect_province(j.location) == priority_province]
            rest_of_canada = lambda jobs: [j for j in jobs if detect_province(j.location) != priority_province]
            sections = [
                (f"📍 Jobs in {province_label}", in_province(coop_jobs)),
                ("🍁 Rest of Canada", rest_of_canada(coop_jobs)),
                (f"🎓📍 New Grad Roles in {province_label}", in_province(new_grad_jobs)),
                ("🎓🍁 New Grad Roles — Rest of Canada", rest_of_canada(new_grad_jobs)),
            ]
        else:
            sections = [(None, coop_jobs), ("🎓 New Grad Roles", new_grad_jobs)]

        posted_jobs = []
        for title, jobs in sections:
            if not jobs:
                continue
            embeds = build_job_embeds(jobs, section_title=title)
            for batch in batch_embeds_by_message(embeds):
                await channel.send(embeds=batch)
            posted_jobs.extend(jobs)

        for job in posted_jobs:
            mark_posted(channel.id, job.id)

        return posted_jobs

    async def scheduled_scrape(self):
        matched_jobs = await asyncio.to_thread(run_pipeline)
        for channel_id, priority_province, include_new_grad in list_channels():
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                logger.warning("Registered channel %s not found/accessible, skipping", channel_id)
                continue
            try:
                posted = await self._post_to_channel(channel, matched_jobs, priority_province, include_new_grad)
                logger.info("Posted %d new job(s) to channel %s", len(posted), channel_id)
            except Exception:
                # One channel failing (permissions revoked, a transient
                # Discord API error, etc.) shouldn't stop every other
                # registered channel from getting posted to.
                logger.exception("Failed to post to channel %s, skipping", channel_id)

    @commands.command(name="help")
    async def help_command(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Frogg 🐸",
            description="Canadian tech co-op/internship postings, delivered to Discord.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="!jobs",
            value="Check for new postings right now in this channel. Requires the channel to be set up first.",
            inline=False,
        )
        embed.add_field(
            name="!status",
            value="Check whether this channel is registered, its priority province, and new grad role setting.",
            inline=False,
        )
        embed.add_field(
            name="!setup",
            value=(
                "Register this channel for automatic postings (12am/6am/12pm/6pm ET), pick "
                'a priority province, and choose whether to include new grad roles. Requires '
                '"Manage Server" permission.'
            ),
            inline=False,
        )
        embed.add_field(
            name="!stop",
            value='Unregister this channel. Requires "Manage Server" permission.',
            inline=False,
        )
        embed.set_footer(text="Once a channel is set up, postings run automatically 4x/day.")
        await ctx.send(embed=embed)

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
        include_new_grad = get_include_new_grad(ctx.channel.id)
        posted = await self._post_to_channel(ctx.channel, matched_jobs, priority_province, include_new_grad)

        if not posted:
            await ctx.send("No new Canadian co-op/internship postings found.")

    @commands.command(name="status")
    async def status(self, ctx: commands.Context):
        if not is_channel_registered(ctx.channel.id):
            await ctx.send("This channel isn't registered. Run `!setup` to register it.")
            return

        priority_province = get_priority_province(ctx.channel.id)
        include_new_grad = get_include_new_grad(ctx.channel.id)
        label = province_name(priority_province) if priority_province else "All of Canada (no preference)"
        new_grad_label = "On" if include_new_grad else "Off"
        await ctx.send(
            "This channel is registered for Frogg postings "
            "(automatically at 12am/6am/12pm/6pm ET).\n"
            f"Priority location: **{label}**.\n"
            f"New grad roles: **{new_grad_label}**."
        )

    @commands.command(name="setup")
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_channel(self, ctx: commands.Context):
        priority_province = get_priority_province(ctx.channel.id)
        include_new_grad = get_include_new_grad(ctx.channel.id)
        view = SetupView(ctx.guild.id, ctx.guild.name, priority_province, include_new_grad)
        view.message = await ctx.send(_setup_status_text(priority_province, include_new_grad), view=view)

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

    @commands.command(name="guilds")
    @commands.is_owner()
    async def guilds(self, ctx: commands.Context):
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        embeds = build_guild_embeds(guilds)

        try:
            for batch in batch_embeds_by_message(embeds):
                await ctx.author.send(embeds=batch)
        except discord.Forbidden:
            await ctx.send("Couldn't DM you — check that DMs from server members are allowed and try again.")
            return

        if ctx.guild is not None:
            await ctx.send("Sent you a DM 🐸")

    @guilds.error
    async def guilds_error(self, ctx: commands.Context, error: commands.CommandError):
        original = getattr(error, "original", error)
        if isinstance(original, commands.NotOwner):
            return  # silently ignore - don't advertise an owner-only command to others
        # Anything else failing here shouldn't just vanish into the logs
        # the way this exact command's Discord API error did - that's
        # what made today's bug invisible until we went digging.
        logger.error("guilds command failed", exc_info=original)
        await ctx.send(f"`!guilds` failed: {original}")


async def setup(bot: commands.Bot):
    await bot.add_cog(JobsCog(bot))
