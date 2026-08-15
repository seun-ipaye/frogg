import asyncio

import discord
from discord.ext import commands

from config import DISCORD_TOKEN
from db import init_db

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")


async def main():
    init_db()
    async with bot:
        await bot.load_extension("cogs.jobs")
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
