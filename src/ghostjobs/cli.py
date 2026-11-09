"""Command line. Run `ghostjobs --help` for the list of commands."""

import argparse
import json
import logging
from pathlib import Path

from sqlmodel import select

from ghostjobs.config import get_settings
from ghostjobs.db import Posting, get_session, init_db, is_active

DEMO_DB = "sqlite:///demo.db"


def main() -> None:
    s = get_settings()
    parser = argparse.ArgumentParser(prog="ghostjobs")
    parser.add_argument("--db", help="Database URL (default: DATABASE_URL from .env)")
    parser.add_argument("--demo", action="store_true", help=f"Shortcut for --db {DEMO_DB}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Scheduled job: all saved searches -> score -> notify")
    r.add_argument("-l", "--location", default=s.default_location)
    r.add_argument("-p", "--pages", type=int, default=s.pages)

    d = sub.add_parser("demo", help="Fill demo.db with fake jobs (no API keys needed)")
    d.add_argument("--notify", action="store_true", help="Also push the genuine ones to your phone")

    f = sub.add_parser("fetch", help="Pull one search from the job boards")
    f.add_argument("-k", "--keywords", default=s.default_keywords)
    f.add_argument("-l", "--location", default=s.default_location)
    f.add_argument("-p", "--pages", type=int, default=s.pages)

    sub.add_parser("score", help="Recompute ghost scores for every stored posting")

    t = sub.add_parser("top", help="List postings, most ghost-like first")
    t.add_argument("-n", type=int, default=15)
    t.add_argument("--genuine", action="store_true", help="Least ghost-like first instead")
    t.add_argument("--all", action="store_true", help="Include adverts that have been taken down")
    t.add_argument(
        "--irrelevant",
        action="store_true",
        help="Show jobs relevance.toml filtered out",
    )

    chk = sub.add_parser("check", help="Test a job title against relevance.toml")
    chk.add_argument("title")

    lab = sub.add_parser("label", help="Record what happened when you applied")
    lab.add_argument("posting_id", type=int)
    lab.add_argument("outcome", choices=["responded", "ghosted", "rejected"])

    cal = sub.add_parser("calibrate", help="Learn scoring weights from your labels")
    cal.add_argument("--apply", action="store_true", help="Save to weights.json and rescore")

    sub.add_parser("notify-test", help="Send a test notification to your phone")
    sub.add_parser("status", help="Show what's set up and what's stored")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "demo" or args.demo:
        s.database_url = DEMO_DB
    if args.db:
        s.database_url = args.db
    init_db()

    # Imported after the DB URL is settled.
    from ghostjobs.notify import Notifier, notify_genuine
    from ghostjobs.pipeline import available_fetchers, fetch_and_store, rescore_all, run_all
    from ghostjobs.scoring import verdict

    with get_session() as session:
        if args.cmd in ("run", "fetch") and not available_fetchers():
            msg = (
                f"No job boards ready (SOURCES={s.sources!r}). Add REED_API_KEY to .env - "
                "or try `ghostjobs demo` in the meantime."
            )
            if args.cmd == "fetch":
                parser.error(msg)
            # Scheduled run before keys exist: warn and exit cleanly rather than fail.
            logging.warning(msg)
            return

        if args.cmd == "run":
            result = run_all(session, args.location, args.pages)
            print(
                f"Fetched {result['fetched']}, scored {result['scored']}, "
                f"notified {result['notified']}."
            )

        elif args.cmd == "demo":
            from ghostjobs.demo import seed

            n = seed(session)
            rescore_all(session)
            print(f"Created {n} fake postings in demo.db.\n")
            print("Try:  ghostjobs --demo top")
            print("      ghostjobs --demo top --genuine")
            print("      ghostjobs --demo top --irrelevant")
            if args.notify:
                sent = notify_genuine(session)
                print(
                    f"\nSent {sent} genuine-looking jobs to your phone."
                    if sent
                    else "\nNothing sent - is NTFY_TOPIC set in .env?"
                )

        elif args.cmd == "fetch":
            n = fetch_and_store(session, args.keywords, args.location, args.pages)
            print(f"Fetched {n} postings. Scoring...")
            rescore_all(session)

        elif args.cmd == "score":
            print(f"Scored {rescore_all(session)} postings.")

        elif args.cmd == "top":
            order = Posting.ghost_score if args.genuine else Posting.ghost_score.desc()
            rows = session.exec(
                select(Posting).where(Posting.ghost_score.is_not(None)).order_by(order)
            ).all()
            if not args.all:
                rows = [p for p in rows if is_active(p)]
            rows = [p for p in rows if p.relevant != args.irrelevant]
            for p in rows[: args.n]:
                if args.irrelevant:
                    print(f"[{p.id}] {p.title} @ {p.company}  -- {p.irrelevant_reason}")
                    continue
                print(
                    f"[{p.id}] {p.ghost_score:5.1f}  {verdict(p.ghost_score):13} "
                    f"{p.title} @ {p.company}  ({p.source})"
                )
                for reason in json.loads(p.reasons or "[]"):
                    print(f"        - {reason}")

        elif args.cmd == "check":
            from ghostjobs.relevance import check_title

            ok, why = check_title(args.title)
            print(f"✓ Relevant: {args.title}" if ok else f"✗ Not relevant: {args.title} ({why})")

        elif args.cmd == "label":
            p = session.get(Posting, args.posting_id)
            if not p:
                parser.error(f"No posting with id {args.posting_id}")
            p.label = args.outcome
            session.add(p)
            session.commit()
            print(f"Labelled {p.title} as {args.outcome}.")

        elif args.cmd == "calibrate":
            from ghostjobs.calibrate import MIN_PER_CLASS, calibrate

            res = calibrate(list(session.exec(select(Posting)).all()))
            print(f"Labels: {res.n_ghost} ghosted, {res.n_real} real (responded/rejected)")
            if not res.enough_data:
                print(f"Need at least {MIN_PER_CLASS} of each to calibrate. Keep labelling!")
                return
            print(f"\n{'signal':<13}{'ghost avg':>10}{'real avg':>10}{'old w':>8}{'new w':>8}")
            for name, g, r_, old, new in res.rows:
                print(f"{name:<13}{g:>10.2f}{r_:>10.2f}{old:>8.2f}{new:>8.2f}")
            if args.apply:
                Path(s.weights_path).write_text(json.dumps(res.weights, indent=2))
                rescore_all(session)
                print(f"\nSaved to {s.weights_path} and rescored everything.")
            else:
                print("\nRun with --apply to use these weights.")

        elif args.cmd == "status":
            from ghostjobs.pipeline import ALL_FETCHERS

            enabled = s.source_list()
            print("Job boards:")
            for name, cls in ALL_FETCHERS.items():
                on = name in enabled
                keys = cls().is_configured()
                state = (
                    "ready"
                    if on and keys
                    else "ON but API key missing in .env"
                    if on
                    else "off (key set, add to SOURCES to use)"
                    if keys
                    else "off"
                )
                print(f"  {name:<8} {state}")
            print(f"Notifications: {'ntfy topic set' if s.ntfy_topic else 'NTFY_TOPIC not set'}")
            print(
                f"Searches:      {'; '.join(s.search_list())}  "
                f"(within {s.search_radius_miles} miles of {s.default_location})"
            )
            rows = list(session.exec(select(Posting)).all())
            open_ = [p for p in rows if is_active(p)]
            print(
                f"Stored jobs:   {len(rows)} total, {len(open_)} still open, "
                f"{sum(p.relevant for p in open_)} relevant to you"
            )
            if rows:
                print(f"Last fetch:    {max(p.last_seen for p in rows):%d %b %Y %H:%M} UTC")

        elif args.cmd == "notify-test":
            n = Notifier()
            if not n.enabled:
                parser.error("Set NTFY_TOPIC in .env first.")
            n.send("Ghost Job Tracker", "Notifications are working 👻", tags="tada")
            print(f"Sent to {n.s.ntfy_server}/{n.s.ntfy_topic}")


if __name__ == "__main__":
    main()
