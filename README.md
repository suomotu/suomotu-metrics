# Suomotu Metrics

*Part of [Suomotu](https://suomotu.dev) — from the Latin* suo motu, *"of its own motion": an organization that runs itself.*

**Prove your AI dev team works.**

Your team adopted AI coding tools, and the question is whether it's working. The data to answer that already sits in your GitHub history — this tool reads it out.

`suomotu-metrics` is a small dockerized tool: point it at a GitHub repository and get a weekly markdown report of engineering metrics for teams where agents write most of the code. It runs on your machine, talks only to the GitHub API, and keeps its data in a local SQLite file. Private repos work with a token that can read them; your numbers stay yours.

## Quickstart

```
mkdir -p data
docker run -v "$PWD/data:/data" -e GITHUB_TOKEN ghcr.io/suomotu/suomotu-metrics owner/repo
```

The report lands in `data/reports/owner-repo/`. To build the image yourself instead:

```
docker build -t suomotu-metrics . && docker run -v "$PWD/data:/data" -e GITHUB_TOKEN suomotu-metrics owner/repo
```

Uncontainered, with Python 3.12 or newer:

```
python -m suomotu_metrics owner/repo --db data/metrics.db --out data/reports
```

A fine-grained read-only token suffices for `GITHUB_TOKEN`. Runs are incremental — the weekly rerun fetches what changed, not the whole history — and a first run bounds its collection to the reporting window (`--weeks`, default 12), so pointing the tool at a decade-old repo stays fast. To report on a longer window, pass a larger `--weeks` on the first run against a fresh database.

## What you get from a bare repo

Ordinary pull requests and CI are enough — the report computes from history your repo already has, with each metric's operational definition printed beside it:

- **First-pass merge share** — how often a change merges from its first implementation pass
- **Lead time** — PR creation to merge
- **Time to first review** and **review time per PR**
- **Change failure rate** — merged work later reverted, or failing CI on its merge commit

## The deeper layer: measuring the chain

Teams that adopt chain-style working — each change starting life as a committed `intent.md`, then `spec.md`, then `plan.md` in a `work/NNN-slug/` folder — unlock a second tier. The tool detects the chain structurally and reports the stage metrics of the AI-native SDLC: intent-to-spec time, spec-to-plan time, plan-to-merge time, and flags for artifacts edited out of order. A bare repo simply gets a complete report without this section.

## Status

v0. This repo is built *by* an agentic development organization that measures itself with this very tool: the first chain the tool detected was the committed intent→spec→plan chain (kept in the organization's own repo) that produced this release, and this repo's PR history is part of that measurement. Roadmap in [ROADMAP.md](ROADMAP.md).

## License

MIT.
