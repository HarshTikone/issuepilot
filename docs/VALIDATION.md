# Validation record

## Automated (every push)

| Check | Result on 2026-11-05 |
|---|---|
| Unit tests, Ubuntu and Windows, Python 3.10 and 3.12 (GitHub Actions) | Run on every push; see the CI badge |
| Unit tests, Linux, Python 3.13 (build session) | 74 passed |
| Line coverage of `issuepilot/` (excluding the CLI entry point) | 87%; CI fails below 80% |
| `ruff check .` | Clean |
| `python -m issuepilot --config config.example.json demo` | One simulated job completed; duplicate discovery added no second comment |

The tests cover the durable workflow, crash recovery, ambiguous comment writes, bounded retries and backoff, quota reservations and cooldowns, provider fallback, error classification, container command restrictions (including keys staying off the host command line), GitHub App token refresh and a real RS256 signature check, bot identity, retrieval filtering and ranking, blob-cache integrity, the report schema, backup and restore, schema migration, benchmark scoring and resumption, and the integrity of every benchmark answer key.

External GitHub, Docker and model behaviour are simulated with controlled substitutes. No real Hermes container, provider, server or GitHub App was used.

## Live validation (not yet performed)

Follow [GO_LIVE.md](GO_LIVE.md) and record dates and links here.

- [ ] Pinned Hermes image starts with the configured restrictions on the target architecture.
- [ ] Gemini and Groq smoke runs return valid reports; `--max-turns` and the custom-endpoint `--api-key` work on that image.
- [ ] A quota error from a real provider is classified and triggers fallback.
- [ ] GitHub App token creation, refresh and bot-identity lookup work; the comment appears as the bot.
- [ ] Automatic polling picks up a new eligible issue without a manual agent launch.
- [ ] Retrieval selects the defect file on a cross-file issue in a real repository.
- [ ] Health endpoints and the heartbeat work on the server.
- [ ] systemd startup, shutdown cleanup, `kill -9` and reboot recovery work.
- [ ] A backup restores into a fresh data directory.
- [ ] The pilot benchmark completes in all three modes and its results are published.
