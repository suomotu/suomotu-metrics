"""Weekly markdown report rendering.

The report is the tool's most-read piece of writing: each number prints with
its operational definition, because a number whose definition lives elsewhere
invites misreading.
"""

from pathlib import Path

from . import __version__, metrics

DEFINITIONS = """\
## How these numbers are computed

**First-pass merge share** counts a merged pull request as first-pass when its
review history contains no "changes requested" verdict and no commits were
pushed after the first review was submitted. A merged PR with no reviews counts
as first-pass. The share is first-pass PRs over merged PRs.

**Lead time** runs from a pull request's creation to its merge, reported as the
median over the PRs merged in the period. For chain-linked work items the
deeper version — plan to merge — appears in the artifact-chain section.

**Time to first review** runs from a pull request's creation to its first
submitted review, reported as the median over reviewed PRs opened in the
period. PRs still in draft are left out. (A PR opened as draft starts this
clock at creation; ready-for-review event timing is a planned refinement.)

**Review time per PR** runs from the first submitted review to the merge,
reported as the median over merged PRs that had a review.

**Change failure rate** counts a merged pull request as failed when its work
was later backed out (a revert landing on the default branch) or a CI run for
its merge commit on the default branch concluded in failure. The rate is
failed PRs over merged PRs.

**Chain stage timings** come from the first commit of each artifact in a
`work/NNN-slug/` folder: intent to spec, spec to plan, and plan to the merge of
the first pull request naming the work item in its branch, title, or body.
A flag appears when an upstream artifact was edited after its successor
existed; in our reading — an opinion, not a verdict — that pattern is worth a
look, since a chain kept only for appearances produces it.

Data source: the GitHub API history of the measured repository. The tool is
read-only toward the repository it measures, and your data stays on your machine.
"""


def format_hours(value):
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value < 1:
        return f"{sign}{value * 60:.0f}m"
    if value < 48:
        return f"{sign}{value:.1f}h"
    return f"{sign}{value / 24:.1f}d"


def format_share(value):
    return "—" if value is None else f"{value * 100:.0f}%"


def render(con, repo_id, full_name, weeks, now):
    tier_one = metrics.compute(con, repo_id, weeks, now)
    chain_items = metrics.compute_chain(con, repo_id)
    summary = tier_one["summary"]

    lines = [
        f"# Suomotu Metrics — {full_name}",
        "",
        f"Generated {now.date().isoformat()} by suomotu-metrics v{__version__} · "
        f"window: trailing {weeks} ISO weeks",
        "",
        "## Summary",
        "",
        "| Metric | Value | Sample |",
        "|---|---|---|",
        f"| First-pass merge share | {format_share(summary['first_pass_share'])} "
        f"| {summary['merged']} merged PRs |",
        f"| Lead time (median) | {format_hours(summary['lead_time_h'])} "
        f"| {summary['merged']} merged PRs |",
        f"| Time to first review (median) | "
        f"{format_hours(summary['time_to_first_review_h'])} "
        f"| {summary['reviewed']} reviewed PRs |",
        f"| Review time per PR (median) | {format_hours(summary['review_time_h'])} "
        f"| {summary['review_sample']} merged PRs with a review |",
        f"| Change failure rate | {format_share(summary['change_failure_rate'])} "
        f"| {summary['merged']} merged PRs |",
        "",
        "## Week by week",
        "",
        "| Week | Merged | First-pass | Lead time | First review | Review time | Failures |",
        "|---|---|---|---|---|---|---|",
    ]
    for week in tier_one["weeks"]:
        lines.append(
            f"| {week['week']} | {week['merged']} "
            f"| {format_share(week['first_pass_share'])} "
            f"| {format_hours(week['lead_time_h'])} "
            f"| {format_hours(week['time_to_first_review_h'])} "
            f"| {format_hours(week['review_time_h'])} "
            f"| {format_share(week['change_failure_rate'])} |"
        )

    if chain_items:
        lines += [
            "",
            "## Artifact chain",
            "",
            "This repository keeps a committed artifact chain "
            "(`work/NNN-slug/` with intent, spec, plan), so the stage metrics "
            "of the AI-native SDLC compute directly from its history:",
            "",
            "| Work item | Intent → spec | Spec → plan | Plan → merge | Linked PRs | Flags |",
            "|---|---|---|---|---|---|",
        ]
        for item in chain_items:
            linked = ", ".join(f"#{n}" for n in item["linked_prs"]) or "—"
            flags = "; ".join(item["flags"]) or "—"
            lines.append(
                f"| {item['folder']} | {format_hours(item['intent_to_spec_h'])} "
                f"| {format_hours(item['spec_to_plan_h'])} "
                f"| {format_hours(item['plan_to_merge_h'])} "
                f"| {linked} | {flags} |"
            )
    else:
        lines += [
            "",
            "_No artifact chain detected — the numbers above come from PR and CI "
            "history alone. Repos that adopt chain-style working (committed "
            "intents, specs, plans in `work/` folders) unlock stage metrics here._",
        ]

    lines += ["", DEFINITIONS]
    return "\n".join(lines)


def write_report(con, repo_id, full_name, weeks, now, out_dir):
    content = render(con, repo_id, full_name, weeks, now)
    folder = Path(out_dir) / full_name.replace("/", "-")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{metrics.iso_week(now)}.md"
    path.write_text(content, encoding="utf-8")
    return path
