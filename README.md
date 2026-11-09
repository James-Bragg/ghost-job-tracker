# Ghost Job Tracker

A headless job-hunting assistant for a Raspberry Pi. Every evening it:

1. pulls UK job adverts from **Reed** (Adzuna is supported too, switched off by default),
2. keeps only the ones **relevant to you** (entry-level tech, within your radius),
3. gives each a 0–100 **ghost score** — how likely it is the advert isn't a real, open role,
4. pushes the genuine-looking new ones to your phone via **ntfy**.

No screen, no dashboard — just a notification with a link you can tap and apply.

---

## Quick start (on the Pi)

Needs 64-bit Raspberry Pi OS (`uname -m` → `aarch64`), Pi 3B+ or newer.

```bash
git clone https://github.com/<you>/ghost-job-tracker.git
cd ghost-job-tracker
bash deploy/pi/install.sh      # 1st run: installs uv + Python 3.12, creates .env, stops
nano .env                      # fill in - see "Configuration" below
bash deploy/pi/install.sh      # 2nd run: test run + installs the daily schedule
~/.local/bin/uv run ghostjobs notify-test
~/.local/bin/uv run ghostjobs status
```

That's it — it now runs every day at **18:00** and survives reboots. If the Pi was off at
18:00, it catches up when it boots.

> `uv` lives in `~/.local/bin`. If plain `uv` isn't found, use `~/.local/bin/uv` or log out
> and back in once. Run all commands from inside the project folder (that's where `.env`
> and the database live).

---

## What you need

| Thing | Where | Cost |
|---|---|---|
| Reed API key | reed.co.uk/developers/jobseeker — sign in, request a key, it's emailed | Free |
| ntfy app | Play Store / App Store, search "ntfy" | Free, no account |
| Adzuna keys (optional) | developer.adzuna.com | Free account = 25 test calls only; full access is a paid plan |

### Phone notifications (ntfy)

1. Install **ntfy**, tap **+**, and subscribe to a topic name you make up.
2. Put the same name in `.env` as `NTFY_TOPIC`.

ntfy doesn't need your phone number or email — the topic name is the only link. Anyone who
knows it can read (and send to) it, so make it **long and random**, e.g.
`job-updates-jb-8k2m9x4q`, never something like `job-updates`.

---

## Configuration (`.env`)

Created from `.env.example` on the first install run. The settings that matter:

```ini
SOURCES=reed                    # reed / adzuna / reed,adzuna
REED_API_KEY=your-key
NTFY_TOPIC=your-long-random-topic

DEFAULT_LOCATION=Corby
SEARCH_RADIUS_MILES=70
PAGES=3                         # 100 results/page on Reed; use 3 for a 50+ mile radius
REED_DETAILS_PER_RUN=150        # full-advert lookups per run (new, relevant jobs only)

SEARCHES=junior developer;graduate developer;junior software engineer;junior web developer;junior python;IT support;1st line support;service desk;helpdesk;IT technician;technical support;application support;junior data analyst;graduate data;software tester;junior QA;junior devops;cyber security graduate;graduate scheme technology
```

Other options (defaults in brackets):

| Setting | What it does |
|---|---|
| `NOTIFY_MAX_SCORE` (30) | Only notify for jobs scoring at or below this |
| `NOTIFY_REQUIRE_SALARY` (false) | Only notify for adverts with a real salary |
| `NOTIFY_MAX_PER_RUN` (5) | Individual alerts per run; the rest arrive as one summary |
| `STALE_AFTER_DAYS` (3) | An advert not seen for this long counts as taken down |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Only used if `adzuna` is in `SOURCES` |

Tips:
- Reed matches **all** words in a search, so keep searches to 2–3 words.
- Overlapping searches are fine — the same job is only stored and notified once.
- Watch for typos in setting names (`PER` not `PRE`) — misspelt settings are silently ignored.
- If `status` shows settings that don't match `.env`, check for leftover shell variables
  with `env | grep -iE "searches|radius|pages"` and `unset` them — they override `.env`.
  (The scheduled run isn't affected; systemd doesn't use your shell's variables.)

---

## Only jobs relevant to you (`relevance.toml`)

Out of the box it's set for **entry-level tech**: development, IT support / service desk,
data, testing, junior infrastructure and security. It filters out:

- senior / lead / manager / architect titles
- tech-sounding jobs that aren't tech (maintenance engineer, IT recruiter, accountant…)
- adverts asking for 3+ years' experience
- adverts needing security clearance
- optionally anything under `min_salary` (off by default)

```bash
nano relevance.toml
uv run ghostjobs check "Senior Python Developer"      # ✗ Not relevant (title contains "Senior")
uv run ghostjobs check "Junior IT Support Technician"  # ✓ Relevant
uv run ghostjobs score                                 # re-apply to everything stored
uv run ghostjobs top --irrelevant -n 40                # what's being filtered, and why
```

Irrelevant jobs are still stored (they help spot agencies posting dozens of adverts) but
never trigger a notification, and Reed's full-advert lookup is skipped for them.

---

## Day to day

**Alerts** show the title, company, location, salary, ghost score and a job number like
`#42`. Tap to open the advert. The first run finds a big backlog — after that, each evening
only brings jobs that are **new** since the last run.

**After you apply**, record what happened (over SSH, e.g. Termius on your phone):

```bash
uv run ghostjobs label 42 ghosted      # or responded / rejected
```

Once you have 5+ ghosted and 5+ responded/rejected:

```bash
uv run ghostjobs calibrate             # shows what it would learn
uv run ghostjobs calibrate --apply     # saves weights.json and rescores everything
```

### Checking it's working

```bash
uv run ghostjobs status                # boards, notifications, searches, jobs stored, last fetch
systemctl list-timers ghostjobs.timer  # next scheduled run
journalctl -u ghostjobs -e             # logs - look for "Fetched …, scored …, notified …"
sudo systemctl start ghostjobs         # run now, exactly as the schedule does
journalctl -u ghostjobs -f             # ...and watch it (Ctrl+C to stop)
```

`notified 0` just means nothing new and genuine turned up since last time.

### Re-sending jobs to your phone

```bash
uv run python -c "import sqlite3; c=sqlite3.connect('ghostjobs.db'); c.execute('update posting set notified=0'); c.commit()"
uv run python -c "from ghostjobs.db import init_db, get_session; from ghostjobs.notify import notify_genuine; init_db(); print(notify_genuine(get_session()), 'sent')"
```

### Changing the schedule

```bash
sudo nano /etc/systemd/system/ghostjobs.timer   # edit OnCalendar=*-*-* 18:00:00 (24h)
sudo systemctl daemon-reload
sudo systemctl restart ghostjobs.timer
```

Also change `deploy/pi/ghostjobs.timer` in the repo so a reinstall keeps it. Don't run it
less than once a day unless you also raise `STALE_AFTER_DAYS`.

### Updating

```bash
git pull
~/.local/bin/uv sync --no-dev
```

Your `.env`, database and `relevance.toml` edits are kept. If `git pull` complains about
`relevance.toml`, run `git stash && git pull && git stash pop`. If the timer file changed,
re-run `bash deploy/pi/install.sh`.

---

## Try it without API keys

```bash
uv run ghostjobs demo                      # ~35 fake jobs with 2 months of history -> demo.db
uv run ghostjobs --demo top                # most ghost-like
uv run ghostjobs --demo top --genuine      # most genuine
uv run ghostjobs --demo top --irrelevant   # what relevance.toml filters out
uv run ghostjobs demo --notify             # push the genuine demo jobs to your phone
```

Demo data lives in its own `demo.db` and never mixes with real data.

---

## How scoring works

| Signal       | What it checks                                                        | Weight |
|--------------|-----------------------------------------------------------------------|--------|
| age          | Days the advert has been up (ramps 14 → 60 days)                      | 0.20   |
| reposts      | Same board + same employer + identical title, different ID            | 0.25   |
| evergreen    | "talent pool", "always looking", "register your interest", etc.       | 0.20   |
| no_salary    | No salary, or only Adzuna's estimate                                  | 0.10   |
| vague        | Buzzwords; very short advert (only judged on full text, not snippets) | 0.10   |
| volume       | Employer has lots of *currently open* adverts                         | 0.10   |
| applications | Huge applicant count (Reed only)                                      | 0.05   |

**0–29 Looks genuine · 30–54 Suspicious · 55+ Likely ghost**

Deliberately ignored: the same job on two boards (normal, not a repost), and taken-down
adverts when counting an employer's open roles. Reed's search only returns a snippet, so
the full advert is fetched once per new relevant job. Default weights are in
`src/ghostjobs/scoring.py`; `calibrate --apply` overrides them from your own results.

---

## Job boards

| Board  | Status | Notes |
|--------|--------|-------|
| Reed   | **On** | Free key. Full adverts + applicant counts. |
| Adzuna | Off    | Code included. Free account = 25 test calls; full access is paid. Add keys and set `SOURCES=reed,adzuna`. |
| Indeed | —      | No public API for reading jobs, and scraping breaks their terms. |

If a board fails during a run (down, bad key, quota used up) it's logged and skipped — the
others still get through. In the logs: `401`/`403` = check the key, `429` = too many calls
(lower `PAGES` or trim `SEARCHES`).

---

## All commands

```bash
uv run ghostjobs run                           # what the schedule runs: fetch -> score -> notify
uv run ghostjobs status
uv run ghostjobs fetch -k "junior developer"   # one search, no notifications
uv run ghostjobs top [--genuine] [--irrelevant] [--all] [-n 20]
uv run ghostjobs check "<job title>"
uv run ghostjobs label <id> ghosted|responded|rejected
uv run ghostjobs calibrate [--apply]
uv run ghostjobs notify-test
uv run ghostjobs demo [--notify]
uv run pytest                                  # tests (needs: uv sync)
```

---

## Project layout

```
.env.example     settings template (copy to .env - never commit .env)
relevance.toml   which jobs are relevant to you
src/ghostjobs/
  config.py      settings from .env
  db.py          SQLite Posting table (+ tiny auto-migration)
  fetchers/      Reed + Adzuna clients -> RawPosting
  relevance.py   applies relevance.toml
  signals.py     posting -> list of 0..1 ghost signals
  scoring.py     signals -> score + reasons
  calibrate.py   learn weights from your labels
  pipeline.py    fetch -> store -> score
  notify.py      ntfy push notifications
  demo.py        fake data for trying it out
  cli.py         the `ghostjobs` command
deploy/pi/       systemd service + timer, install.sh
tests/
```

Built with Python 3.12, httpx, SQLModel/SQLite, pydantic-settings, rapidfuzz, uv and systemd.

---

## Roadmap

- [x] Reed integration, relevance filter, phone notifications
- [x] Runs daily on the Pi
- [ ] Label 50+ outcomes and run `calibrate --apply`
- [ ] `ghostjobs notify --resend` command; quieter logs
- [ ] Second free board (Jooble)
- [ ] Company context: careers-page check, layoff news