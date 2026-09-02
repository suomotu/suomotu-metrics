# Suomotu Metrics

*Part of [Suomotu](https://suomotu.dev) — from the Latin* suo motu, *"of its own motion": an organization that runs itself.*

**Prove your AI dev team works.**

Your team adopted AI coding tools. Your board, your investors, and your own gut are asking the same question: is it working? The data to answer that already sits in your GitHub history — this tool reads it out.

`suomotu-metrics` is a small dockerized tool: point it at a GitHub repository and get a weekly markdown report of the engineering metrics that matter where agents write most of the code. It runs on your machine, talks to the GitHub API and to nowhere else, and keeps its data in a local SQLite file. Private repos work with a token that can read them; your numbers stay yours.

## Quickstart

```
mkdir -p data
docker run -v "$PWD/data:/data" -e GITHUB_TOKEN ghcr.io/suomotu/suomotu-metrics owner/repo
```

The report lands in `data/reports/owner-repo/`. To build the image yourself instead:

```
docker build -t suomotu-metrics . && docker run -v "$PWD/data:/data" -e GITHUB_TOKEN suomotu-metrics owner/repo
```

Uncontainered, with Python 3.12 or newer: `python -m suomotu_metrics owner/repo` (flags: `--db`, `--out`, `--weeks`). A fine-grained read-only token suffices for `GITHUB_TOKEN`. Runs are incremental — the weekly rerun fetches what changed, not the whole history.

## What you get from a bare repo

Ordinary pull requests and CI are enough — no methodology change, no signup. From that history alone the report computes, with each metric's operational definition printed beside it:

- **First-pass merge share** — how often a change merges from its first implementation pass
- **Lead time** — PR creation to merge
- **Time to first review** and **review time per PR**
- **Change failure rate** — merged work later reverted, or failing CI on its merge commit

## The deeper layer: measuring the chain

Teams that adopt chain-style working — each change starting life as a committed `intent.md`, then `spec.md`, then `plan.md` in a `work/NNN-slug/` folder — unlock a second tier. The tool detects the chain structurally and reports the stage metrics of the AI-native SDLC: intent-to-spec time, spec-to-plan time, plan-to-merge time, and flags for artifacts edited out of order. A bare repo simply gets a complete report without this section.

## Status

v0. This repo is built *by* an agentic development organization that measures itself with this very tool — its own artifact chain was the first the tool detected, and the commit history here is the live demo. Roadmap in [ROADMAP.md](ROADMAP.md).

## License

MIT.
