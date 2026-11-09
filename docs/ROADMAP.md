# IssuePilot roadmap

The code for milestones 1 to 5 is in place and unit-tested (74 tests, 87% line coverage). What remains needs your own accounts: a live model run, a free Linux server, a GitHub App installation and a measured benchmark. Those steps are in [GO_LIVE.md](GO_LIVE.md). [The design notes](DESIGN_NOTES.md) explain each decision.

The release targets published free allowances. It does not promise uninterrupted free hosting.

## 1. Publish and establish the baseline

- [x] Publish the source, tests, deployment tools and documentation.
- [x] Windows and Ubuntu CI on Python 3.10 and 3.12, plus lint and a coverage floor.
- [x] Package metadata, console command and MIT license.
- [x] Keep simulated output visibly distinct from live investigations.

## 2. Prove one free inference provider

- [x] Typed investigator result with provider, model, timing and attempt log; typed errors with category and retry delay.
- [x] Custom endpoints through explicit `--base-url` launch settings, with the key kept off the host command line.
- [x] Reserve requests and tokens per provider before each run; skip providers whose per-request ceiling the snapshot exceeds.
- [x] Bound tool turns, retries and fallback; cool down a provider until its reset; defer jobs without spending attempts.
- [ ] **Live:** smoke-test Gemini and Groq on the pinned Hermes digest (`smoke-agent --provider NAME`).

## 3. Deploy the investigator

- [x] GitHub App installation tokens with refresh and bot identity; personal-token mode kept as a fallback.
- [x] Consistent online backup, checked restore, queue-age and failure health signals, optional heartbeat.
- [x] Setup wizard and guide for Oracle Always Free, free model keys and App mode.
- [ ] **Live:** provision the server, check the arm64 image, install the App and start the service.
- [ ] **Live:** observe automatic pickup of a new issue; test restart, `kill -9` and reboot recovery; restore a backup once.
- [ ] **Live:** record discovery, queue and model time separately for the first issues.

## 4. Retrieve source context

- [x] Filter tree metadata at one commit; fail on truncation.
- [x] Fetch at most 40 candidates through a cache keyed and verified by Git blob SHA.
- [x] Rank with BM25, path matches and import links; enforce file, byte and token budgets.
- [x] Reject symlinks, submodules, hidden, vendor, generated, binary, secret-like and oversized files.
- [x] Record the selected files and scores on each job.
- [ ] Let the model request additional files, subject to the same checks.

## 5. Run a pilot benchmark

- [x] Separate bug, needs-information and injection cases (12, 4 and 4), with answer keys outside agent input.
- [x] `needs_information` outcome with zero citations allowed; short citation spans required.
- [x] Score citation hits, right file, diagnosis terms, abstention, useful questions and injection resistance separately.
- [x] Oracle-context, retrieval and all-files modes with the same router and budget rules.
- [x] Resumable runs that share the serving quota ledger; manual and weekly workflow with dated summaries.
- [ ] **Live:** run all three modes and publish the per-case results with model, image digest and prompt ID.
- [ ] Write 5 held-out cases privately in `eval/heldout/` and run them once, after tuning is finished.

The cases are small (2–4 files), so retrieval mode is nearly the same as all-files. Treat results as a pilot, not a reliability estimate. If a baseline beats the agent, publish that.

## 6. Add restricted draft PRs (optional)

- [ ] Grant Contents write and Pull requests write to the supervisor only when this feature is enabled.
- [ ] Validate patch paths, modes and size against an exact base commit.
- [ ] Keep trusted tests and commands outside model-writable paths.
- [ ] Run tests in a prebuilt, non-root, network-disabled, resource-limited runner without credentials or a Docker socket.
- [ ] Require regression tests to fail on the base and pass on the patch, on the exact proposed commit.
- [ ] Reconcile branch and PR creation after ambiguous responses; publish only bounded, redacted diagnostics.

## Release evidence

Publish real issue and comment links, the checked source commit, runtime digest, sanitized benchmark results and a short demo. State measured uptime and cost with a date range. Describe duplicate handling as durable retries with reconciliation; external GitHub writes are not guaranteed to happen exactly once.
