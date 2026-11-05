# Changelog

## 0.2.0 — 2026-11-05

- Provider routing for free tiers: ordered providers, per-provider request and token reservations, cooldowns, fallback on quota and outage errors, and deferral without spending attempts.
- Groq and other OpenAI-compatible endpoints through Hermes's `custom` provider, with the key kept off the host command line. Only the selected provider's key enters the container.
- GitHub App authentication with repository-scoped installation tokens, refresh and bot identity.
- Source retrieval from the repository tree with safety filters, a SHA-verified blob cache, BM25, path and import ranking, and token budgets.
- Report schema: `needs_information` outcome with questions, and bounded citation spans.
- `backup`, `restore` and `usage` commands; richer health signals; optional heartbeat.
- 20-case pilot benchmark with separate bug, abstention and injection scores, three context modes, resumable runs and a manual or weekly workflow.
- Packaging, MIT license, ruff lint and a coverage floor in CI.

## 0.1.0 — 2026-11-05

- Durable GitHub poller and SQLite queue, Hermes container adapter, strict report validation, offline demo and Ubuntu service tooling.
