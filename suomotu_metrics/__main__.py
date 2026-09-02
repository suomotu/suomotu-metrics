"""Command-line entry point.

Built to run unattended: no prompts, exit 0 when each requested report is
produced, non-zero with a one-line diagnostic on failure.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

from . import collect, db, metrics, report
from .github import Client, GitHubError

SUBCOMMANDS = ("run", "collect", "report")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="suomotu-metrics",
        description="Weekly engineering metrics from a GitHub repository's history.",
    )
    parser.add_argument("command", choices=SUBCOMMANDS, help="what to do")
    parser.add_argument("repos", nargs="+", metavar="owner/repo")
    parser.add_argument("--db", default="/data/metrics.db", help="SQLite file path")
    parser.add_argument("--out", default="/data/reports", help="report output directory")
    parser.add_argument("--weeks", type=int, default=12, help="trailing ISO weeks")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Default subcommand: owner/repo arguments contain "/", so a bare token
    # equal to a subcommand name is unambiguous.
    if argv and not any(token in SUBCOMMANDS for token in argv):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)

    client = None
    if args.command in ("run", "collect"):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print(
                "suomotu-metrics: set GITHUB_TOKEN (a read-only token works)",
                file=sys.stderr,
            )
            return 2
        client = Client(token)

    now = datetime.now(timezone.utc)
    try:
        con = db.connect(args.db)
    except (sqlite3.OperationalError, OSError) as error:
        print(
            f"suomotu-metrics: cannot open database at {args.db} ({error}) — "
            "pass a writable path with --db",
            file=sys.stderr,
        )
        return 1
    cutoff = metrics.window_start(now, args.weeks).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        for full_name in args.repos:
            if full_name.count("/") != 1:
                print(f"suomotu-metrics: '{full_name}' is not owner/repo", file=sys.stderr)
                return 2
            if args.command in ("run", "collect"):
                summary = collect.collect_repo(con, client, full_name, cutoff)
                print(
                    f"collected {full_name}: {summary['new_prs']} PRs updated, "
                    f"{summary['new_runs']} CI runs, {summary['new_reverts']} reverts, "
                    f"{summary['work_items']} chain work items"
                )
            if args.command in ("run", "report"):
                repo_id = db.get_repo_id(con, full_name)
                if repo_id is None:
                    print(
                        f"suomotu-metrics: no collected data for {full_name} — "
                        "run collect first",
                        file=sys.stderr,
                    )
                    return 2
                path = report.write_report(
                    con, repo_id, full_name, args.weeks, now, args.out
                )
                print(f"report: {path}")
    except GitHubError as error:
        print(f"suomotu-metrics: {error}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
