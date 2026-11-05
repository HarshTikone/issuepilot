# IssuePilot roadmap

The current implementation provides a durable issue queue, a Docker adapter for Hermes, strict report validation, a simulated demo and Ubuntu service tooling. Forty automated checks pass locally. Live model execution, Linux deployment and the GitHub App integration still need verification.

The next release targets published free allowances. It does not promise uninterrupted free hosting. [The upgrade-plan review](UPGRADE_PLAN_REVIEW.md) records the integration and evaluation changes needed before implementation.

## 1. Publish and establish the baseline

- [ ] Publish the source, tests, deployment tools and documentation as separate commits.
- [ ] Verify the Windows and Ubuntu CI jobs in the actual repository.
- [ ] Record the application commit and local validation results.
- [ ] Keep simulated output visibly distinct from live investigations.

Completion: a reviewer can clone the project, run the tests and reproduce the offline demo.

## 2. Prove one free inference provider

- [ ] Introduce a typed investigator result with provider/model, usage, timing and error category.
- [ ] Resolve custom-endpoint configuration without relying on a file ignored by Hermes safe mode.
- [ ] Smoke-test Groq against an exact Hermes image digest and a tool-capable model available to the account.
- [ ] Record each inference request and reserve request/token quota before issuing it.
- [ ] Bound tool turns, output length, retries and provider fallback; respect quota reset times.
- [ ] Add Gemini/OpenRouter only after the first provider path works.

Completion: one real investigation returns a validated report, its actual model usage is recorded, and exhausted quotas cause a controlled wait or failure.

## 3. Deploy the investigator

- [ ] Provision an Always Free Oracle instance if capacity is available; verify the account's current allowance.
- [ ] SSH into Ubuntu and check the pinned ARM image on the actual server.
- [ ] Implement GitHub App installation authentication, token refresh and bot actor identification.
- [ ] Configure the repository installation, issue author policy and work label.
- [ ] Start the systemd service and observe automatic pickup of a new issue.
- [ ] Check restart, forced-process termination and reboot recovery.
- [ ] Add heartbeat and job-failure monitoring, then test a consistent database backup/restore.

Completion: an already-running service handles real issues without manual agent commands, and the resulting comments link to the source revision inspected. Measure discovery, queue and execution time separately.

## 4. Retrieve source context

- [ ] Fetch and validate repository-tree metadata at one commit; handle truncation.
- [ ] Fetch bounded candidate contents and cache them by blob SHA.
- [ ] Rank paths and text with a lexical index before asking the model for additional files.
- [ ] Enforce file, byte and token budgets for every retrieval round.
- [ ] Reject untrusted paths, symlinks, submodules, binary/generated/vendor files and sensitive files.
- [ ] Record the selected files and revision for reproducibility.

Completion: retrieval finds the relevant source on distinct cross-file issues without a hand-picked file list. The report can cite only files actually retrieved.

## 5. Run a pilot benchmark

- [ ] Define separate bug, insufficient-information and injection outcomes.
- [ ] Update the schema so a justified request for information can have zero source citations.
- [ ] Score root-cause explanations and short citation spans separately.
- [ ] Keep answer keys outside agent inputs and use synthetic injection canaries.
- [ ] Compare oracle-context, retrieved-context and all-files baselines using the same model and budget rules.
- [ ] Keep a genuinely held-out set, publish sanitized per-case results and record runtime/model/prompt versions.
- [ ] Pace runs within the shared serving/evaluation quota and support resuming partial runs.
- [ ] Add a manual evaluation trigger and a results-freshness indicator.

Completion: publish measured outcomes with explicit denominators. A baseline may outperform the agent; report the result. Twenty small cases are a pilot, not a general reliability guarantee.

## 6. Add restricted draft PRs

- [ ] Grant the supervisor Contents write and Pull requests write only when this feature is enabled.
- [ ] Validate patch paths, modes and size against an exact base commit.
- [ ] Keep trusted tests and commands outside model-writable paths.
- [ ] Use a prebuilt dependency image in a non-root, network-disabled, resource-limited runner without credentials or a Docker socket.
- [ ] Require regression tests to fail on the base and pass on the patch.
- [ ] Check the exact proposed commit and handle base-branch movement.
- [ ] Reconcile branch/PR creation after ambiguous responses.
- [ ] Publish bounded, redacted diagnostics when checks fail.

Completion: an eligible issue produces a draft PR with verified checks and human review required before merge. This phase is optional until the live investigator and evaluation work.

## Release evidence

Publish real issue/comment links, the checked source commit, runtime digest, sanitized evaluation results and a short operating demo. State measured uptime and costs with a date range. Describe duplicate handling as durable retries with reconciliation; external GitHub writes are not guaranteed to occur exactly once.
