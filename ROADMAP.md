# Roadmap

## v0 — measure any repo, and the chain where one exists
- GitHub API collector → SQLite: PRs, reviews, CI runs
- Weekly report (markdown): first-pass merge share, lead time, review time, time to first review, change failure rate
- Artifact-chain detection: `work/NNN-*/` folders (intent/spec/plan) yield stage metrics — intent→spec time, spec→plan time, plan→merge time, out-of-order edit flags
- Docker image; single-command run against any repo

## v0.2 — agent-native metrics
- Ingest telemetry (cost, human touches) from instrumented repos; report cost per shipped change
- Diff-matches-plan rate, once a recorded conformance-verdict format exists (timestamps compute mechanically; plan conformance takes judgment)

## Later
- HTML report theme, multi-repo dashboards, historical trends
- Ready-for-review event timing for draft PRs
