# Frogg

A Discord bot that scrapes Canadian tech co-op and internship postings from
Greenhouse, Lever, and Workday career pages, dedupes them against a local
SQLite database, and posts new ones as embeds — automatically every 6 hours,
or on demand with `!jobs`.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- `DISCORD_TOKEN` — your bot's token from the [Discord Developer Portal](https://discord.com/developers/applications)
- `DISCORD_CHANNEL_ID` — the channel ID postings get sent to
- `DATABASE_PATH` — defaults to `frogg.db` locally

Run it:

```bash
python bot.py
```

## Deploying to Railway

1. Create a new Railway project from this GitHub repo.
2. Add a **volume** and mount it at `/data` — this is where the SQLite
   database persists across deploys/restarts. Without it, the dedup history
   resets every time the service redeploys.
3. Set environment variables in the Railway service:
   - `DISCORD_TOKEN`
   - `DISCORD_CHANNEL_ID`
   - `DATABASE_PATH=/data/frogg.db`
4. Railway picks up the `Procfile` (`worker: python bot.py`) automatically.
   Deploy — the bot stays connected as a persistent worker (no sleep).

## Adding a company

Companies are registered in `scrapers/companies.py`, grouped by which ATS
they use (Greenhouse board token, Lever company token, or Workday
tenant/host/site). Add an entry to the relevant dict and it's picked up by
both the manual command and the scheduled scrape automatically.
