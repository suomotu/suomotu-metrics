# Roadmap

## v0 — measure any repo
- GitHub API collector → SQLite: PRs, reviews, CI runs
- Weekly report (markdown): first-pass merge share, lead time, review time, time to first review, change failure rate
- Docker image; single-command run against any repo

## v0.1 — measure the artifact chain
- Detect `work/NNN-*/` artifact chains (intent/spec/plan) and compute stage metrics: intent→spec time, spec→plan time, plan-approval→merge time, diff-matches-plan rate

## v0.2 — agent-native metrics
- Ingest telemetry (cost, human touches) from instrumented repos; report cost per shipped change

## Later
- HTML report theme, multi-repo dashboards, historical trends
