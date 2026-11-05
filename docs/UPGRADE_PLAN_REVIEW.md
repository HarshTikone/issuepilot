# Review of the free-stack upgrade plan

Reviewed on November 5, 2026 against the ten-page November 4 free-stack plan, the current IssuePilot implementation, and the official references below. The original PDF stays local. The plan proposes future work. Its deployment, benchmark and PR results have not happened yet.

The direction is workable: get one real issue investigation running, add retrieval, measure it, then attempt draft PRs. Several details need changing before those steps will work reliably.

## Fix before the first provider integration

### 1. Count model requests and tokens, not only jobs

Pages 1 and 7 treat `max_jobs_per_day` as protection for model quotas. In the current worker it limits investigator starts. A single Hermes investigation can make several inference requests as it reads files, reasons, retries, or switches providers. Retrieval adds another request, and evaluation uses the same provider allowance.

Groq currently lists 30 requests/minute, 1,000 requests/day, **8,000 tokens/minute**, and 200,000 tokens/day for the named model in its published limits table. Exact limits depend on the account. The plan omits the per-minute token limit, which can be reached long before the daily allowance. A 60KB source cap also does not guarantee that a request fits within a token budget. See [Groq rate limits](https://console.groq.com/docs/rate-limits).

Add a persisted ledger per provider/account/model for requests, input/output tokens, reserved budget and reset times. Apply limits before each actual model request. Reserve room for system instructions, tool definitions, file reads and the answer. Bound tool iterations and output tokens, respect `Retry-After`, and share the budget between serving issues and evaluation. A ledger fed only after a whole job completes cannot enforce a strict request-level quota.

The estimate that twenty cases fit into one day is a hypothesis to measure. Twenty cases across three baselines require sixty task runs; retries and tool turns multiply the inference requests. Pace them and resume incomplete evaluations instead of promising a full run always fits.

### 2. Resolve the Hermes safe-mode/configuration conflict

Pages 3 and 4 propose mounting `config.yaml` to configure Groq. The current container command uses `--safe-mode`, which ignores user configuration. Mounting a file alone will not make that command read the custom endpoint. The provider-secret parser also accepts only API-key variables; it does not currently forward an endpoint URL.

Choose one tested mechanism for the pinned Hermes version: explicit endpoint launch settings or a minimal trusted configuration that preserves the intended restrictions. Do not remove safety flags without replacing their behavior. Add a live Groq smoke test that verifies the actual endpoint, model, tool calls and output contract. The [Hermes CLI documentation](https://hermes-agent.nousresearch.com/docs/user-guide/cli) describes the configuration bypass and explicit launch settings.

### 3. Define how fallback detects quota errors

The current adapter turns a nonzero container exit into a generic `RuntimeError`; the supervisor does not receive a structured HTTP 429. The instruction to fall back on 429 therefore needs a transport or runtime change.

Define a typed result/error contract containing provider, model, error category, retry time and usage when available. Retry transient failures with limits, cool down an exhausted provider until reset, and stop cleanly if every provider is exhausted. Record failed attempts as well as the final provider. Avoid cycling providers for an invalid prompt or repeatedly retrying malformed output without a separate bound.

## Fix before live deployment

### 4. GitHub App authentication is more than replacing a token

Page 5 omits installation-token refresh and bot identity changes. Installation tokens expire after one hour. The current code calls `/user` to identify the owner of a report comment; that endpoint supports user tokens and fine-grained personal tokens, not installation tokens.

Implement token creation/refresh from the App credentials and installation ID, retain the reported expiration, and refresh before expiry. Determine the App bot actor independently and use it for comment reconciliation. Handle token expiry during a job without repeating an external write. Also make the installation/repository mapping explicit for the second repository used in the deployment test.

References: [installation token lifetime](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app), [authenticated-user token support](https://docs.github.com/en/rest/users/users#get-the-authenticated-user).

### 5. Treat zero recurring charges and 24/7 operation as targets

The plan's current Oracle allocation is supported: the Always Free documentation lists 2 OCPUs and 12GB for A1. It also documents regional capacity limitations and reclamation of idle instances. A lightly used issue bot can fall into the idle category. A rebuild script reduces recovery effort; it does not provide uninterrupted availability. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Use wording such as "designed to stay within published free allowances" until a real billing period and uptime have been measured. Do not generate wasteful load to defeat idle reclamation.

The Google e2-micro fallback is not equivalent to a zero-risk free server. It needs a billing account, the trial has an end, and external IPv4 has separate pricing. This conflicts with the plan's card-for-identity-only rule unless explicitly accepted. WSL2 is useful for development, but depends on your computer staying awake and does not establish that you deployed to a remote Linux server over SSH.

References: [Google Cloud free-program requirements](https://docs.cloud.google.com/free/docs/free-cloud-features), [external IP pricing](https://cloud.google.com/vpc/network-pricing#ipaddress).

### 6. Make backup and health behavior explicit

Page 8 suggests backing up the live SQLite file to a private repository. Copying a database while it is being written can produce an inconsistent backup. Use SQLite's online backup API, or stop the worker for the snapshot. Run an integrity check, encrypt sensitive backups before upload, set retention, and test restoration. Keep App keys and provider credentials out of backups. See [SQLite's backup API](https://www.sqlite.org/backup.html).

A health ping after each cycle proves the loop ran. It can still look healthy while every model task fails or the queue grows. Track last successful GitHub poll, last successful model task, oldest queued job and terminal failures separately. Set the heartbeat grace period above the bounded task duration and polling interval. An empty queue should not count as a failure.

The three-minute report target should specify an empty queue, available quota and a healthy provider. Queue wait and model duration should be reported separately. The current four-minute task timeout cannot guarantee a three-minute end-to-end result.

## Fix before retrieval and evaluation

### 7. A repository tree is not a text index

Page 5 proposes BM25 over paths, symbols and file text after one Git Trees API call. That response provides tree/blob metadata, not the contents needed for text ranking or symbol extraction. Large recursive responses can also be truncated.

Use the tree to filter candidates, then fetch bounded blobs or build a cached index from a pinned repository snapshot. Cache by commit/blob SHA, exclude generated/vendor/binary/secret-bearing files, and handle truncated trees explicitly. Only downloaded files from the pinned revision can enter the validated context. Treat the model's requested paths as suggestions that must pass the same checks. See [Git Trees API behavior](https://docs.github.com/en/rest/git/trees#get-a-tree).

### 8. Separate the benchmark tasks and make abstention possible

Pages 6 and 7 mix twelve explicit bug cases, four vague issues and four injection cases. The last eight do not necessarily have a valid root-cause answer. Report separate scores for bug diagnosis, retrieval, abstention and injection behavior. If an injection case also contains a bug, define both labels and denominators explicitly.

The current report validator requires at least one source-evidence entry. A vague issue may have no defensible citation. Add a `needs_information` outcome that can have zero evidence, names the missing facts and asks a useful question. Merely adding any assumption should not earn an uncertainty pass.

Line overlap alone can reward citing an entire file. Restrict the number and total length of cited spans, then score whether the explanation identifies the defect. Report citation accuracy separately from semantic diagnosis. Keep answer keys out of the agent's mounted input.

Use synthetic canaries for injection tests. Do not use genuine GitHub or model credentials as benchmark targets. Check allowed tool use and output behavior, then publish sanitized results and describe exactly what four passing cases establish.

Run baselines with the same model, source revision, prompt task, retry rules and total token allowance. A hand-picked-file baseline is an oracle-context comparison and should be labelled that way. With tiny one-to-five-file snapshots, the all-files baseline may reasonably win. Publish that result if it does; the evaluation should not require the agent to beat it.

The five held-out cases must remain untouched until evaluation. If you examine their failures to tune the system, replace them before the next held-out claim. Record model IDs, runtime digest, prompts, seeds where supported, and run timestamps. Treat twenty small cases as a pilot benchmark, not a general reliability estimate.

## Fix before draft PRs

### 9. Add write permissions and a trusted patch/test boundary

The phase-2 App has Contents read and Issues read/write. Phase 5 also needs Contents write to publish a branch/commit and Pull requests write to create a draft PR. Keep those rights in the supervisor; do not give its token to the agent or test runner. See [PR creation permissions](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request).

Before applying a patch, validate both old and new paths, reject absolute paths and traversal, reject symlinks/submodules and sensitive workflow/configuration paths, and enforce change-size limits. Bind it to an exact base SHA. Use a disposable worktree and check the result before packaging a commit.

Prebuild a trusted test image with pinned dependencies. A network-disabled runner cannot install missing packages. Fix the test command outside the model's output, run as non-root with resource limits, and mount neither credentials nor a Docker socket. Repository tests are executable code, so keep the initial fix feature limited to repositories you explicitly trust.

Run the original regression test against the base and the patched version: it should fail before the change and pass afterward. Keep trusted tests outside model-writable paths so deleting tests or changing the test command cannot manufacture success. Treat no-tests-collected, timeouts and setup failures as failures.

Re-run checks on the exact commit proposed for the PR. If the default branch moved, rebase/re-evaluate before claiming the patch passed. Reconcile branches and PRs after ambiguous API responses just as reports are reconciled.

Do not automatically post raw failing output as page 6 proposes. Bound, escape and redact it first; tests can print sensitive values or repository-controlled text.

## Claims and schedule

Page 10 says recovery happens without duplicate comments, and page 6 proposes a blog post about exactly-once posting. The current persist-before-post and marker checks reduce duplicates, but GitHub comment creation has no atomic idempotency key. A lost response plus delayed comment visibility can still duplicate a post. Keep the narrower claim: durable retries with comment reconciliation.

The public weekly evaluation should have a manual trigger and a stale-results indicator. GitHub can delay scheduled work, and public schedules can be disabled after sixty days without repository activity. See [scheduled-workflow behavior](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows).

The PDF's phase-six text ends on day 33; its chart ends on December 11 when starting November 9. Those are different schedules. Use one dated plan with a buffer for free-server capacity, provider compatibility and App authentication.

Keep draft PR mode optional until the live investigator and pilot benchmark work. The existing forty unit tests are useful, but they do not establish real ARM image compatibility, actual model output, App token refresh, CI execution or Linux recovery. Add those as explicit integration checks.

## Recommended order

1. Publish the current implementation and clearly label its local validation status.
2. Prove one free provider using the pinned runtime, then add request/token accounting.
3. Deploy to Oracle if capacity is available; implement App authentication and recovery checks.
4. Add retrieval with a bounded cached source index.
5. Run separate diagnosis, abstention and injection evaluations, including fair baselines.
6. Attempt restricted draft PRs only after the trusted patch/test boundary is complete.

This order retains the useful parts of the five-week plan and makes each completion claim independently checkable.
