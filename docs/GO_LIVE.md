# Go-live checklist

Everything here needs your own accounts, so it cannot be done from the code alone. Work top to bottom; each step lists what to keep as evidence. Total cost: $0, as long as you stay within each provider's published free allowance.

## 1. Model keys and a pinned runtime (about 1 hour)

- [ ] Create a Gemini key in Google AI Studio and, optionally, a Groq key. Copy each account's real limits into `rpm`, `rpd`, `tpm` and `tpd` in your config.
- [ ] On any Linux machine with Docker, pull `nousresearch/hermes-agent:stable` and record its digest and `--version`.
- [ ] Run `python -m issuepilot --config config.json smoke-agent --provider gemini`, then `--provider groq`.
- [ ] If a run fails, check the two untested launch details in [DEPLOYMENT.md](DEPLOYMENT.md) step 8 (`--max-turns`, and `--api-key` for the custom endpoint).

Keep: image digest, Hermes version, provider and model IDs, and the two `hermes-smoke-*.json` reports.

## 2. Free server (about 2 hours, plus waiting for capacity)

- [ ] Create the Oracle Always Free A1 instance (DEPLOYMENT.md step 3) and log in over SSH with your own key.
- [ ] Confirm the Hermes image architecture is `arm64`.
- [ ] Install the service, run the wizard and `admin.sh check`.

Keep: a sanitized terminal capture showing `uname -a`, `/etc/os-release` and `systemctl status issuepilot`.

## 3. GitHub App and automatic pickup (about 1 hour)

- [ ] Create and install the App on this repository only; copy its key to `/etc/issuepilot/app.pem`.
- [ ] Start the service. With it already running, open a labelled issue from the browser and wait.
- [ ] Confirm the comment comes from `<app-name>[bot]` and links to the inspected commit.
- [ ] Repeat with a second issue whose cause is in a different file than the symptom (retrieval enabled).
- [ ] Restart, `kill -9` the worker, and reboot; confirm no duplicate comment and that the next issue is handled.
- [ ] Take one backup and practise one restore.

Keep: issue and comment URLs, timestamps for discovery, queue and model time, and the recovery capture.

## 4. Benchmark (spread over 2–3 days to stay inside free quotas)

- [ ] Add repository secrets `GEMINI_API_KEY` and/or `GROQ_API_KEY` and the repository variable `HERMES_IMAGE` (the pinned digest).
- [ ] Run the **Pilot benchmark** workflow manually for `retrieval`, `oracle` and `all-files`. If a run stops on quota, run it again later; it resumes that week's results.
- [ ] Download the artifacts and copy each mode's summary table into the README's Results section with the run date.
- [ ] Write 5 held-out cases in `eval/heldout/` (ignored by Git) and run them once, at the end.

Keep: the result JSONL files, model IDs, image digest and prompt ID from each row.

## 5. Show it

- [ ] Record a 60–90 second screen capture: label an issue, the bot's comment appears, open a cited line.
- [ ] Add one screenshot or GIF of a real comment to the README.
- [ ] Update VALIDATION.md with the live results and dates.

## What you can claim, and when

| After | You can say |
|---|---|
| Now | Built and unit-tested provider routing with quota reservations, GitHub App auth, retrieval and a 20-case pilot benchmark |
| Step 1 | Ran real Hermes Agent investigations on free Gemini and Groq tiers |
| Steps 2–3 | Deployed and operated a self-hosted agent on Linux with systemd that answers GitHub issues automatically |
| Step 4 | The measured X/12 root-cause citation rate, Y/4 abstentions and Z/4 injection resists, with the date and model |

Keep the duplicate-handling claim narrow: durable retries with reconciliation, not exactly-once delivery.
