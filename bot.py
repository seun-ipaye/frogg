import asyncio
import logging

import discord
from discord.ext import commands

from config import DISCORD_TOKEN
from db import init_db
from topgg_stats import post_server_count

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    await post_server_count(bot)


@bot.event
async def on_guild_join(guild: discord.Guild):
    await post_server_count(bot)


@bot.event
async def on_guild_remove(guild: discord.Guild):
    await post_server_count(bot)


async def main():
    discord.utils.setup_logging()
    init_db()
    async with bot:
        await bot.load_extension("cogs.jobs")
        try:
            await bot.load_extension("cogs.listings_sync")
        except Exception:
            # The repo sync is optional; whatever goes wrong with it must not stop the bot starting.
            logging.getLogger(__name__).exception("Listings sync not loaded")
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
