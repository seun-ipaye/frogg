import asyncio

import discord
from discord.ext import commands

from config import DISCORD_CHANNEL_ID
from pipeline import run_pipeline
from scrapers.base import Job


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

    @commands.command(name="jobs")
    async def jobs(self, ctx: commands.Context):
        await ctx.send("Scraping for new postings...")
        new_jobs = await asyncio.to_thread(run_pipeline)

        if not new_jobs:
            await ctx.send("No new Canadian co-op/internship postings found.")
            return

        channel = self.bot.get_channel(DISCORD_CHANNEL_ID) or ctx.channel
        for job in new_jobs:
            await channel.send(embed=job_to_embed(job))


async def setup(bot: commands.Bot):
    await bot.add_cog(JobsCog(bot))
