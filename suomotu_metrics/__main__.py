"""Command-line entry point.

Built to run unattended: no prompts, exit 0 when each requested report is
produced, non-zero with a one-line diagnostic on failure.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from . import collect, db, report
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
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
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
    con = db.connect(args.db)
    try:
        for full_name in args.repos:
            if full_name.count("/") != 1:
                print(f"suomotu-metrics: '{full_name}' is not owner/repo", file=sys.stderr)
                return 2
            if args.command in ("run", "collect"):
                summary = collect.collect_repo(con, client, full_name)
                print(
                    f"collected {full_name}: {summary['new_prs']} PRs updated, "
                    f"{summary['new_runs']} CI runs, {summary['new_reverts']} reverts, "
                    f"{summary['work_items']} chain work items"
                )
            if args.command in ("run", "report"):
                row = con.execute(
                    "SELECT id FROM repos WHERE full_name = ?", (full_name,)
                ).fetchone()
                if row is None:
                    print(
                        f"suomotu-metrics: no collected data for {full_name} — "
                        "run collect first",
                        file=sys.stderr,
                    )
                    return 2
                path = report.write_report(
                    con, row["id"], full_name, args.weeks, now, args.out
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
