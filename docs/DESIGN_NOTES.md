# Design notes: running IssuePilot on free tiers

These notes record a review, on November 5, 2026, of a five-week plan to run IssuePilot entirely on free services. Each section states a problem in that plan, the decision taken, and its status in the code. "Implemented" means unit-tested here; it does not mean verified against a live provider, server or GitHub App. Live checks are tracked in [GO_LIVE.md](GO_LIVE.md).

The direction is workable: get one real issue investigation running, add retrieval, measure it, then attempt draft PRs. Several details needed changing first.

## Fix before the first provider integration

### 1. Count model requests and tokens, not only jobs

**Status: implemented.** `Store.reserve_usage` reserves `max_turns` requests and a pessimistic token estimate per provider before every run, across serving and evaluation. Per-request size is checked against `tpm` and `max_input_tokens`. Hermes does not report per-request usage to IssuePilot, so the ledger records reservations, not measured usage.

The plan treated `max_jobs_per_day` as protection for model quotas. In the current worker it limits investigator starts. A single Hermes investigation can make several inference requests as it reads files, reasons, retries, or switches providers. Retrieval adds another request, and evaluation uses the same provider allowance.

Groq currently lists 30 requests/minute, 1,000 requests/day, **8,000 tokens/minute**, and 200,000 tokens/day for the named model in its published limits table. Exact limits depend on the account. The plan omits the per-minute token limit, which can be reached long before the daily allowance. A 60KB source cap also does not guarantee that a request fits within a token budget. See [Groq rate limits](https://console.groq.com/docs/rate-limits).

Add a persisted ledger per provider/account/model for requests, input/output tokens, reserved budget and reset times. Apply limits before each actual model request. Reserve room for system instructions, tool definitions, file reads and the answer. Bound tool iterations and output tokens, respect `Retry-After`, and share the budget between serving issues and evaluation. A ledger fed only after a whole job completes cannot enforce a strict request-level quota.

The estimate that twenty cases fit into one day is a hypothesis to measure. Twenty cases across three baselines require sixty task runs; retries and tool turns multiply the inference requests. Pace them and resume incomplete evaluations instead of promising a full run always fits.

### 2. Resolve the Hermes safe-mode/configuration conflict

**Status: implemented, live check pending.** Groq uses `--provider custom --base-url`; the key is expanded from `IP_MODEL_KEY` inside the container and never appears in host argv. Only the selected provider's key is forwarded. Verify on the pinned image with `smoke-agent --provider groq`.

The plan proposed mounting `config.yaml` to configure Groq. The current container command uses `--safe-mode`, which ignores user configuration. Mounting a file alone will not make that command read the custom endpoint. The provider-secret parser also accepts only API-key variables; it does not currently forward an endpoint URL.

Choose one tested mechanism for the pinned Hermes version: explicit endpoint launch settings or a minimal trusted configuration that preserves the intended restrictions. Do not remove safety flags without replacing their behavior. Add a live Groq smoke test that verifies the actual endpoint, model, tool calls and output contract. The [Hermes CLI documentation](https://hermes-agent.nousresearch.com/docs/user-guide/cli) describes the configuration bypass and explicit launch settings.

### 3. Define how fallback detects quota errors

**Status: implemented.** `InvestigatorError` carries a category (`quota`, `too_large`, `auth`, `unavailable`, `runtime`) and a retry delay parsed from the error text, which is then discarded. Quota and outage errors cool the provider down and fall back. Malformed output and runtime errors are not retried on another provider. When every provider is waiting, the job is deferred without spending an attempt.

The current adapter turns a nonzero container exit into a generic `RuntimeError`; the supervisor does not receive a structured HTTP 429. The instruction to fall back on 429 therefore needs a transport or runtime change.

Define a typed result/error contract containing provider, model, error category, retry time and usage when available. Retry transient failures with limits, cool down an exhausted provider until reset, and stop cleanly if every provider is exhausted. Record failed attempts as well as the final provider. Avoid cycling providers for an invalid prompt or repeatedly retrying malformed output without a separate bound.

## Fix before live deployment

### 4. GitHub App authentication is more than replacing a token

**Status: implemented, live check pending.** `AppAuth` signs an RS256 JWT, requests a repository-scoped installation token, refreshes it 5 minutes before expiry and drops it on HTTP 401. The bot's user ID comes from `GET /app` and `GET /users/<slug>[bot]`. A second repository needs its own installation and data directory.

The plan omitted installation-token refresh and bot identity changes. Installation tokens expire after one hour. The current code calls `/user` to identify the owner of a report comment; that endpoint supports user tokens and fine-grained personal tokens, not installation tokens.

Implement token creation/refresh from the App credentials and installation ID, retain the reported expiration, and refresh before expiry. Determine the App bot actor independently and use it for comment reconciliation. Handle token expiry during a job without repeating an external write. Also make the installation/repository mapping explicit for the second repository used in the deployment test.

References: [installation token lifetime](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [authenticated-user token support](https://docs.github.com/en/rest/users/users#get-the-authenticated-user).

### 5. Treat zero recurring charges and 24/7 operation as targets

**Status: adopted in docs.** README and roadmap say "designed to stay within published free allowances". The Google e2-micro fallback was dropped.

The plan's current Oracle allocation is supported: the Always Free documentation lists 2 OCPUs and 12GB for A1. It also documents regional capacity limitations and reclamation of idle instances. A lightly used issue bot can fall into the idle category. A rebuild script reduces recovery effort; it does not provide uninterrupted availability. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Use wording such as "designed to stay within published free allowances" until a real billing period and uptime have been measured. Do not generate wasteful load to defeat idle reclamation.

The Google e2-micro fallback is not equivalent to a zero-risk free server. It needs a billing account, the trial has an end, and external IPv4 has separate pricing. This conflicts with the plan's card-for-identity-only rule unless explicitly accepted. WSL2 is useful for development, but depends on your computer staying awake and does not establish that you deployed to a remote Linux server over SSH.

References: [Google Cloud free-program requirements](https://docs.cloud.google.com/free/docs/free-cloud-features), [external IP pricing](https://cloud.google.com/vpc/network-pricing#ipaddress).

### 6. Make backup and health behavior explicit

**Status: implemented.** `backup` uses SQLite's online backup API plus `integrity_check`, and `restore` refuses to overwrite a database. Health reports the oldest queued job, last success and failed jobs. The optional heartbeat pings `/fail` on poll errors or new job failures.

The plan suggested backing up the live SQLite file to a private repository. Copying a database while it is being written can produce an inconsistent backup. Use SQLite's online backup API, or stop the worker for the snapshot. Run an integrity check, encrypt sensitive backups before upload, set retention, and test restoration. Keep App keys and provider credentials out of backups. See [SQLite's backup API](https://www.sqlite.org/backup.html).

A health ping after each cycle proves the loop ran. It can still look healthy while every model task fails or the queue grows. Track last successful GitHub poll, last successful model task, oldest queued job and terminal failures separately. Set the heartbeat grace period above the bounded task duration and polling interval. An empty queue should not count as a failure.

The three-minute report target should specify an empty queue, available quota and a healthy provider. Queue wait and model duration should be reported separately. The current four-minute task timeout cannot guarantee a three-minute end-to-end result.

## Fix before retrieval and evaluation

### 7. A repository tree is not a text index

**Status: implemented.** Retrieval filters tree entries (symlinks, submodules, hidden, vendor, generated, binary, secret-like and oversized files), fails on a truncated tree, fetches at most 40 candidate blobs through a SHA-verified cache, and ranks with BM25 plus path matches and import links. Model-requested extra files are not implemented.

The plan proposeds BM25 over paths, symbols and file text after one Git Trees API call. That response provides tree/blob metadata, not the contents needed for text ranking or symbol extraction. Large recursive responses can also be truncated.

Use the tree to filter candidates, then fetch bounded blobs or build a cached index from a pinned repository snapshot. Cache by commit/blob SHA, exclude generated/vendor/binary/secret-bearing files, and handle truncated trees explicitly. Only downloaded files from the pinned revision can enter the validated context. Treat the model's requested paths as suggestions that must pass the same checks. See [Git Trees API behavior](https://docs.github.com/en/rest/git/trees#get-a-tree).

### 8. Separate the benchmark tasks and make abstention possible

**Status: implemented.** The schema has a `needs_information` outcome with questions and optional evidence. Spans are capped at 40 lines and 120 in total. The benchmark scores bug, abstention and injection cases separately, uses synthetic canaries, and labels the hand-picked mode as oracle context.

The plan mixed twelve explicit bug cases, four vague issues and four injection cases. The last eight do not necessarily have a valid root-cause answer. Report separate scores for bug diagnosis, retrieval, abstention and injection behavior. If an injection case also contains a bug, define both labels and denominators explicitly.

The current report validator requires at least one source-evidence entry. A vague issue may have no defensible citation. Add a `needs_information` outcome that can have zero evidence, names the missing facts and asks a useful question. Merely adding any assumption should not earn an uncertainty pass.

Line overlap alone can reward citing an entire file. Restrict the number and total length of cited spans, then score whether the explanation identifies the defect. Report citation accuracy separately from semantic diagnosis. Keep answer keys out of the agent's mounted input.

Use synthetic canaries for injection tests. Do not use genuine GitHub or model credentials as benchmark targets. Check allowed tool use and output behavior, then publish sanitized results and describe exactly what four passing cases establish.

Run baselines with the same model, source revision, prompt task, retry rules and total token allowance. A hand-picked-file baseline is an oracle-context comparison and should be labelled that way. With tiny one-to-five-file snapshots, the all-files baseline may reasonably win. Publish that result if it does; the evaluation should not require the agent to beat it.

The five held-out cases must remain untouched until evaluation. If you examine their failures to tune the system, replace them before the next held-out claim. Record model IDs, runtime digest, prompts, seeds where supported, and run timestamps. Treat twenty small cases as a pilot benchmark, not a general reliability estimate.

## Fix before draft PRs

### 9. Add write permissions and a trusted patch/test boundary

**Status: not started.** Draft PR mode remains optional and follows the live investigator.

The plan's App had Contents read and Issues read/write. Phase 5 also needs Contents write to publish a branch/commit and Pull requests write to create a draft PR. Keep those rights in the supervisor; do not give its token to the agent or test runner. See [PR creation permissions](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request).

Before applying a patch, validate both old and new paths, reject absolute paths and traversal, reject symlinks/submodules and sensitive workflow/configuration paths, and enforce change-size limits. Bind it to an exact base SHA. Use a disposable worktree and check the result before packaging a commit.

Prebuild a trusted test image with pinned dependencies. A network-disabled runner cannot install missing packages. Fix the test command outside the model's output, run as non-root with resource limits, and mount neither credentials nor a Docker socket. Repository tests are executable code, so keep the initial fix feature limited to repositories you explicitly trust.

Run the original regression test against the base and the patched version: it should fail before the change and pass afterward. Keep trusted tests outside model-writable paths so deleting tests or changing the test command cannot manufacture success. Treat no-tests-collected, timeouts and setup failures as failures.

Re-run checks on the exact commit proposed for the PR. If the default branch moved, rebase/re-evaluate before claiming the patch passed. Reconcile branches and PRs after ambiguous API responses just as reports are reconciled.

Do not automatically post raw failing output as the plan proposed. Bound, escape and redact it first; tests can print sensitive values or repository-controlled text.

## Claims and schedule

The plan's resume bullet said recovery happens without duplicate comments, and it proposed a blog post about exactly-once posting. The current persist-before-post and marker checks reduce duplicates, but GitHub comment creation has no atomic idempotency key. A lost response plus delayed comment visibility can still duplicate a post. Keep the narrower claim: durable retries with comment reconciliation.

The public weekly evaluation should have a manual trigger and a stale-results indicator. GitHub can delay scheduled work, and public schedules can be disabled after sixty days without repository activity. See [scheduled-workflow behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

Day 33 and December 11 describe the same schedule (November 9 is day 1). Even so, keep one dated plan with a buffer for free-server capacity, provider compatibility and App authentication.

Keep draft PR mode optional until the live investigator and pilot benchmark work. The existing forty unit tests are useful, but they do not establish real ARM image compatibility, actual model output, App token refresh, CI execution or Linux recovery. Add those as explicit integration checks.

## Two further constraints

**Groq's per-minute limit caps a single request.** The published free limit is 8,000 tokens per minute. A full 60KB snapshot is roughly 15,000–20,000 tokens with line-number framing, so it cannot be served even after waiting. The router skips Groq for such snapshots, and the live config lists Gemini first. Several quick tool turns can still exceed the minute limit; those return 429 and fall back.

**Never pass a model key on the host command line.** A `--api-key` argument on the `docker run` command line is visible to any local user through the process list. The key stays in the container environment and is expanded by a shell inside the container.

## Recommended order

1. Publish the current implementation and clearly label its local validation status.
2. Prove one free provider using the pinned runtime, then add request/token accounting.
3. Deploy to Oracle if capacity is available; implement App authentication and recovery checks.
4. Add retrieval with a bounded cached source index.
5. Run separate diagnosis, abstention and injection evaluations, including fair baselines.
6. Attempt restricted draft PRs only after the trusted patch/test boundary is complete.

This order retains the useful parts of the five-week plan and makes each completion claim independently checkable.
