# Ghost Job Tracker

Runs headless on a Raspberry Pi. Three times a day it pulls UK job postings from Reed
(Adzuna is supported too, switched off by default), keeps only the ones **relevant to you**, gives each a 0–100 **ghost score** (how
likely it is that the advert isn't a real, open role), and pushes the genuine-looking ones to
your phone.

## Setup

```bash
# install uv: https://docs.astral.sh/uv/
uv sync
cp .env.example .env    # then add REED_API_KEY + NTFY_TOPIC
```

## Try it without API keys

```bash
uv run ghostjobs demo                      # ~35 fake jobs with 2 months of history -> demo.db
uv run ghostjobs --demo top                # most ghost-like
uv run ghostjobs --demo top --genuine      # most genuine
uv run ghostjobs --demo top --irrelevant   # what relevance.toml filtered out, and why
uv run ghostjobs demo --notify             # also push the genuine ones to your phone
```

Demo data lives in its own `demo.db`, so it never mixes with your real data.

## Job boards

| Board  | Cost | Status | Setup |
|--------|------|--------|-------|
| Reed   | Free | **On** by default | Get a key at reed.co.uk/developers/jobseeker (emailed), set `REED_API_KEY` |
| Adzuna | Free account = 25 test calls only; full access is a paid plan (£8/month at time of writing) | Off by default | Set `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, then `SOURCES=reed,adzuna` |

`uv run ghostjobs status` shows which boards are ready. If one board fails during a run
(down, bad key, quota used up) it's logged and skipped - the others still get through and
you still get notified.

## Only jobs relevant to you

`relevance.toml` decides what you get told about. Out of the box it's set for
**entry-level tech roles** (development, IT support / service desk, data, testing, junior
infrastructure and security) and filters out:

- senior / lead / manager / architect titles
- tech-sounding jobs that aren't tech (maintenance engineer, IT recruiter, accountant...)
- adverts asking for 3+ years' experience
- adverts needing security clearance
- optionally, anything under a minimum salary (`min_salary`, off by default)

Edit it with `nano relevance.toml`, then check a title:

```bash
uv run ghostjobs check "Senior Python Developer"     # ✗ Not relevant (title contains "Senior")
uv run ghostjobs check "Junior IT Support Technician" # ✓ Relevant
uv run ghostjobs score                                # re-apply to everything stored
uv run ghostjobs top --irrelevant                     # see what's being filtered and why
```

Irrelevant jobs are still stored (they help spot agencies posting dozens of adverts), but
they never trigger a notification, and Reed's full-advert lookup is skipped for them to
save API calls. The searches themselves are in `.env` as `SEARCHES`.

## Phone notifications

Uses [ntfy](https://ntfy.sh) — free, no account needed.

1. Install the **ntfy** app on your phone (Play Store / App Store).
2. Make up a long random topic name, e.g. `ghostjobs-james-7f3k9q2x`
   (anyone who knows the name can read it, so don't use something guessable).
3. In the app, tap **+** and subscribe to that topic.
4. Put it in `.env` as `NTFY_TOPIC=...` and run `uv run ghostjobs notify-test`.

Each run, any **relevant, still-open** job with a ghost score at or below `NOTIFY_MAX_SCORE`
(default 30) that you haven't been told about yet is pushed to your phone — tap it to open
the advert. A job listed on both Reed and Adzuna only alerts once. The first run will find a
backlog, so only `NOTIFY_MAX_PER_RUN` arrive individually and the rest come as one summary.

Every notification ends with the job's number (e.g. `#42`), so you can record what happened
after you apply — from your phone, over SSH (e.g. Termius):

```bash
cd ~/ghost-job-tracker
~/.local/bin/uv run ghostjobs label 42 ghosted     # or responded / rejected
```

## Running on a Raspberry Pi

Works on any Pi running 64-bit Raspberry Pi OS (Pi 3B+ or newer). No screen needed.

```bash
git clone <your repo> ~/ghost-job-tracker   # or copy the folder over
cd ~/ghost-job-tracker
bash deploy/pi/install.sh            # first time: creates .env, then stops
nano .env                            # add NTFY_TOPIC (+ REED_API_KEY when you have it)
bash deploy/pi/install.sh            # installs, does a test run, schedules it
```

This installs [uv](https://docs.astral.sh/uv/) (which fetches Python 3.12 — Pi OS ships an
older one), does a test run, then sets up a systemd timer that runs at 08:00, 13:00 and 18:00
If the Pi was off, it catches up on boot. You can install before your Reed key arrives -
runs just log a warning until you add it to `.env`.

```bash
systemctl list-timers ghostjobs.timer     # when's the next run
sudo systemctl start ghostjobs            # run now
journalctl -u ghostjobs -e                # logs
```

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

0–29 **Looks genuine** · 30–54 **Suspicious** · 55+ **Likely ghost**

Things it deliberately ignores: the same job on Reed *and* Adzuna (normal, not a repost),
and adverts that have been taken down (not seen for `STALE_AFTER_DAYS`, default 3) when
counting how many roles an employer has open. Reed only returns a snippet in search results,
so the full advert is fetched once for each new relevant job.

### Tuning the weights from your own results

```bash
uv run ghostjobs label 42 ghosted      # or responded / rejected
uv run ghostjobs calibrate             # once you have 5+ ghosted and 5+ real
uv run ghostjobs calibrate --apply     # saves weights.json and rescores
```

Default weights live in `src/ghostjobs/scoring.py`.

## All commands

```bash
uv run ghostjobs run                  # what the Pi runs: all SEARCHES -> score -> notify
uv run ghostjobs fetch -k "junior developer"   # one search, no notifications
uv run ghostjobs top [--genuine] [--irrelevant] [--all]
uv run ghostjobs check "<job title>"
uv run ghostjobs label <id> ghosted|responded|rejected
uv run ghostjobs calibrate [--apply]
uv run ghostjobs notify-test
uv run ghostjobs status               # boards, notifications, how many jobs stored
uv run pytest
```

## Layout

```
relevance.toml   which jobs are relevant to you
src/ghostjobs/
  config.py      settings from .env
  db.py          SQLModel Posting table
  fetchers/      Adzuna + Reed clients -> RawPosting
  relevance.py   applies relevance.toml
  signals.py     posting -> list of 0..1 signals
  scoring.py     signals -> score + reasons
  calibrate.py   learn weights from your labels
  pipeline.py    fetch -> store -> score
  notify.py      ntfy push notifications
  demo.py        fake data for trying it out
  cli.py         `ghostjobs` command
deploy/pi/       systemd service + timer, install.sh
tests/
```

## Roadmap

- [ ] Get API keys, first run
- [ ] Set up on the Pi + ntfy
- [ ] Company context: careers-page check, layoff news
- [ ] Label 50+ outcomes, run `calibrate --apply`
