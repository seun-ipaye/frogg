import logging

import aiohttp

from config import TOPGG_TOKEN

logger = logging.getLogger(__name__)

TOPGG_STATS_URL = "https://top.gg/api/bots/{bot_id}/stats"


async def post_server_count(bot) -> None:
    """Report the bot's current guild count to top.gg.

    top.gg has no way to know how many servers a listed bot is actually
    in unless the bot tells it - the listing otherwise shows a stale or
    unset number. No-ops if TOPGG_TOKEN isn't configured.
    """
    if not TOPGG_TOKEN:
        return

    server_count = len(bot.guilds)
    url = TOPGG_STATS_URL.format(bot_id=bot.user.id)
    headers = {"Authorization": TOPGG_TOKEN}
    payload = {"server_count": server_count}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    logger.info("Posted server count to top.gg: %d", server_count)
                else:
                    body = await response.text()
                    logger.warning("top.gg stats post failed (%s): %s", response.status, body)
    except Exception:
        logger.exception("Failed to post server count to top.gg")
