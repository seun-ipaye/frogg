# Frogg

A Discord bot that scrapes Canadian tech co-op and internship postings from
Greenhouse, Lever, and Workday career pages, plus a community internship
tracker, dedupes them against a local SQLite database, and posts new ones
as embeds — automatically at 12am/6am/12pm/6pm ET, or on demand with
`!jobs`. Works across any number of servers: each one registers its own
channel with `!setup`.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- `DISCORD_TOKEN` — your bot's token from the [Discord Developer Portal](https://discord.com/developers/applications)
- `DATABASE_PATH` — defaults to `frogg.db` locally

Run it:

```bash
python bot.py
```

Then, in any server the bot's been invited to, someone with "Manage
Server" permission runs `!setup` in the channel that should receive
postings. Run `!stop` in a channel to unregister it.

## Deploying to Railway

1. Create a new Railway project from this GitHub repo.
2. Add a **volume** and mount it at `/data` — this is where the SQLite
   database persists across deploys/restarts. Without it, the dedup history
   *and* the list of registered channels reset every time the service
   redeploys.
3. Set environment variables in the Railway service:
   - `DISCORD_TOKEN`
   - `DATABASE_PATH=/data/frogg.db`
4. Railway picks up the `Procfile` (`worker: python bot.py`) automatically.
   Deploy — the bot stays connected as a persistent worker (no sleep).
5. Run `!setup` in each server's target channel (see above) — channels
   aren't registered automatically.

## Adding a company

Companies are registered in `scrapers/companies.py`, grouped by which ATS
they use (Greenhouse board token, Lever company token, or Workday
tenant/host/site). Add an entry to the relevant dict and it's picked up by
both the manual command and the scheduled scrape automatically.
