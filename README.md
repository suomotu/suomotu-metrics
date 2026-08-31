# Suomotu Metrics

*Part of [Suomotu](https://suomotu.dev) — from the Latin* suo motu, *"of its own motion": an organization that runs itself.*

**Prove your AI dev team works.**

A small, dockerized tool that measures an AI-native development lifecycle from the evidence it already leaves behind: pull-request and CI history, and — where a repo keeps them — the committed artifact chain (`intent.md → spec.md → plan.md`).

It reports the metrics that matter for teams where agents write most of the code:

- **First-pass merge share** — how often a change merges from its first implementation pass
- **Lead time** — plan approval to merged PR
- **Review time per PR** and **time to first review**
- **Change failure rate**
- and, for instrumented repos: **cost per shipped change** and **human touches per change**

Weekly reports as markdown/HTML, backed by SQLite. Point it at any GitHub repo.

## Status

Pre-v0. This repo is being built *by* an agentic development organization measuring itself with this very tool — the commit history here is the live demo. Roadmap in [ROADMAP.md](ROADMAP.md).

## Why this exists

"The agentic dev team is improving" should be a measurable claim, not a vibe. The AI-native SDLC defines per-stage leading and lagging metrics; this tool collects them.

## License

MIT.
