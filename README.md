<a href="https://top.gg/bot/1538298422807765002">
  <img src="https://top.gg/api/widget/1538298422807765002.svg">
</a>

# Frogg

A Discord bot that scrapes Canadian tech co-op, internship, and new grad
postings from Greenhouse, Lever, and Workday career pages, plus two
community trackers, dedupes them against a local SQLite database, and
posts new ones as embeds — automatically at 12am/6am/12pm/6pm ET, or on
demand with `!jobs`. Works across any number of servers: each one
registers its own channel with `!setup`.

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
postings. Two independent dropdowns appear: a priority province (or
"All of Canada" for a single combined list) and whether to include new
grad roles alongside co-ops/internships. Picking a province splits
posts into an in-province section and a rest-of-Canada section; with
new grad roles on, those get their own matching sections too. Run
`!setup` again anytime to change either choice, or `!stop` to
unregister the channel entirely.

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

## Publishing listings to a public GitHub repo

Every 30 minutes (`LISTINGS_SYNC_INTERVAL_MINUTES`) Frogg updates a **separate**
public repo with all currently open Canadian co-op/internship listings:
`listings.json` (the source of truth a landing page can read), a generated
`README.md` with tables grouped by term, and `archive.json` (listings closed for
more than 30 days). Discord posting is independent and keeps its own schedule;
if the sync fails it's logged and retried, nothing else is affected.

1. **Create the repo** — public, and separate from this one (Railway redeploys
   the bot on every push here). Tick "Add a README" so the branch exists.
2. **Create a token** — GitHub → Settings → Developer settings → Personal access
   tokens → Fine-grained tokens. Limit it to *only that repo* with
   **Contents: Read and write**.
3. **Set env vars** in your local `.env` and in Railway (never commit them):
   `GITHUB_TOKEN`, `GITHUB_REPO=owner/name`, and optionally `GITHUB_BRANCH` and
   `BOT_INVITE_URL` (the "add to server" link shown in the generated README). Without these the sync
   stays off.
4. **Preview before going live** — set `LISTINGS_OUTPUT_DIR` to a local clone of
   the listings repo and run `python -m listings`. It writes the files there
   without touching git or the network push path (it wins over `GITHUB_*`), so
   you can review and commit by hand.
5. **Add topic tags** in the repo's About panel (the token can't set these):
   `canadian-tech-internships`, `canada-coop`, `internships-2027`, `swe-internships`.

Listings close after 3 consecutive complete scrapes where they're missing from
their source. If the database volume is ever lost, history (`date_found`, closed
dates) is restored from the published `listings.json`. The data comes from the
SimplifyJobs community trackers, which declare no license, so the generated
README credits them. Run the tests with `python -m unittest discover -s tests -t .`.
