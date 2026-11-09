# Your first SSH deployment: Windows → Ubuntu → GitHub

You currently have a GitHub account, but no Linux server. SSH is the secure connection you use to log into that server. A cloud provider supplies the server's IP address; your public/private key pair supplies your login credentials.

You should perform the SSH login, deployment and verification yourself. Assistance is useful, but a project folder alone does not establish that you personally deployed to Linux.

## 1. Publish the project to your GitHub account

If `HarshTikone/issuepilot` has already been published, clone it and skip the initialization commands below. Otherwise, create an empty repository named `issuepilot` under [HarshTikone](https://github.com/HarshTikone). Do not initialize it with another README.

Open PowerShell in the delivered `issuepilot` folder and run:

```powershell
git init -b main
git add .
git status --short
git commit -m "Build IssuePilot autonomous Hermes investigator"
git remote add origin https://github.com/HarshTikone/issuepilot.git
git push -u origin main
```

Use GitHub's normal browser sign-in if prompted by Git Credential Manager. The account profile URL is not a repository remote. If Git asks for your author name/email, configure the identity you normally use for GitHub, then retry the commit. Confirm the repository contains `issuepilot/`, `tests/`, `deploy/`, `docs/`, and `demo_app/` at its root. Check the Actions tab for CI results.

In the repository, create an issue label named `agent-ready`.

## 2. Create an SSH key on your Windows computer

These commands run locally in PowerShell, not on the server. The dedicated name avoids overwriting a key used for other services.

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
Test-Path "$env:USERPROFILE\.ssh\issuepilot_ed25519"
```

If the result is `True`, reuse that dedicated key if appropriate or choose a new filename. Do not overwrite an existing private key. If `False`, generate it:

```powershell
ssh-keygen -t ed25519 -C "issuepilot-vps" -f "$env:USERPROFILE\.ssh\issuepilot_ed25519"
```

Choose a passphrase when prompted. Display the **public** key:

```powershell
Get-Content "$env:USERPROFILE\.ssh\issuepilot_ed25519.pub"
```

The `.pub` file can be uploaded to your VPS provider. The file without `.pub` is private: keep it on your computer. This uses the standard OpenSSH key workflow documented by [DigitalOcean](https://docs.digitalocean.com/products/droplets/how-to/add-ssh-keys/create-with-openssh/).

## 3. Create a free Linux server

The free path is an [Oracle Cloud Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) Ampere A1 instance. Its documentation lists 2 OCPUs and 12GB of memory for A1 in total. Read the current page before you create anything, because the allowance has changed before.

- Choose your home region carefully at sign-up; it cannot be changed later. Arm capacity is sometimes unavailable, so retry later if creation fails.
- Create one **VM.Standard.A1.Flex** instance with Ubuntu 24.04 (aarch64), at most 2 OCPUs and 12GB, and a boot volume within the free storage allowance.
- Oracle documents that idle Always Free instances can be reclaimed. Do not generate artificial load to avoid this. Keep the setup reproducible and back up the job database (see Routine operation).
- Upload the public key from step 2. In the subnet's security list, allow inbound TCP 22 **only from your current public IP**. No other inbound port is needed.

A paid VPS such as a [DigitalOcean Droplet](https://docs.digitalocean.com/products/droplets/how-to/create/) works the same way if Oracle capacity is unavailable. Review its price and set a billing alert first.

Oracle's default login user for Ubuntu images is `ubuntu`, not `root`. The control panel shows the public address; use it as `YOUR_SERVER_IP`.

## 4. Log in over SSH yourself

In local PowerShell:

```powershell
$issuepilotServer = "YOUR_SERVER_IP"
ssh -i "$env:USERPROFILE\.ssh\issuepilot_ed25519" "ubuntu@$issuepilotServer"
```

On the first connection, verify the host-key fingerprint through your provider's trusted console or documented fingerprint procedure before accepting it. Enter your key passphrase when prompted.

When your prompt changes to the remote Ubuntu shell, run:

```bash
whoami
hostname
uname -a
cat /etc/os-release
```

This is the start of your actual Linux deployment experience. Keep a sanitized terminal capture for your evidence folder.

## 5. Prepare the Ubuntu server

The commands from here through step 10 run **inside the SSH session**.

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git python3 python3-cryptography ca-certificates curl
```

Install Docker Engine using [Docker's official Ubuntu apt-repository instructions](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository). Use the repository installation rather than downloading an unrelated setup script. Then verify:

```bash
sudo systemctl enable --now docker
sudo docker version
python3 --version
df -h /
free -h
```

Clone the public repository you published in step 1:

```bash
sudo git clone https://github.com/HarshTikone/issuepilot.git /opt/issuepilot
cd /opt/issuepilot
python3 -m unittest discover -s tests -v
sudo docker pull nousresearch/hermes-agent:stable
sudo docker image inspect nousresearch/hermes-agent:stable --format '{{index .RepoDigests 0}}'
sudo docker image inspect nousresearch/hermes-agent:stable --format '{{.Architecture}}'
sudo docker run --rm nousresearch/hermes-agent:stable --version
```

On Oracle's Arm server the architecture must print `arm64`. If the image has no arm64 build, stop here: use an x86 server or build Hermes from source, and record that change.

The [official Hermes Docker documentation](https://hermes-agent.nousresearch.com/docs/user-guide/docker) provides this image family. Its stable tag can change; the setup wizard records the exact downloaded digest for IssuePilot's task executions. Save the printed version and digest.

If you choose a private repository, clone using your normal GitHub SSH/deploy-key setup. Do not put a token into the clone URL or shell history. IssuePilot's separate runtime token does not need repository write access.

## 6. Create scoped runtime credentials

**GitHub identity (recommended: a GitHub App).** In GitHub Settings → Developer settings → GitHub Apps, create an App with no webhook and these repository permissions:

| Repository permission | Access |
|---|---|
| Contents | Read-only |
| Issues | Read and write |
| Metadata | Read-only, automatically included |

Install it on **only `HarshTikone/issuepilot`**. Note the App ID and the installation ID (the number at the end of the installation's settings URL), then generate a private key. Copy the `.pem` file to the server as `/etc/issuepilot/app.pem` after step 7's install script creates that folder:

```bash
sudo install -o root -g issuepilot -m 0640 app.pem /etc/issuepilot/app.pem && rm app.pem
```

IssuePilot requests a one-hour installation token scoped to this repository and refreshes it before expiry. Comments appear as `your-app-name[bot]`. See [installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).

The fallback is an expiring fine-grained personal token for only this repository with the same permissions. Comments then appear under your account.

**Model keys (free tiers).** Create a key in [Google AI Studio](https://aistudio.google.com/) for Gemini and, optionally, a key in the [Groq console](https://console.groq.com/). Check each account's current rate limits: Gemini shows them on the AI Studio rate-limit page, and Groq on its limits page. Copy those numbers into `rpm`, `rpd`, `tpm` and `tpd` in the config so IssuePilot reserves budget before each run. Free-tier prompts may be used to improve the provider's products, so only use repositories whose code you are willing to share.

Groq's free plan allows about 8,000 tokens per minute. A full 60KB snapshot cannot fit in one minute's allowance, so IssuePilot skips Groq for large snapshots and tries the next provider. Keep Gemini first for live issues.

Keep the keys in your password manager while setting up. Do not paste them into chat, issues, commits, screenshots or terminal commands.

## 7. Install and configure IssuePilot

```bash
cd /opt/issuepilot
sudo bash deploy/install-service.sh
# App mode only: copy the private key now (see step 6), then run the wizard.
sudo python3 deploy/configure.py
```

The wizard asks for your model keys and model IDs, and for either the GitHub App IDs or a token. Key input is hidden and not stored in shell history. It creates:

| File | Purpose |
|---|---|
| `/etc/issuepilot/config.json` | Repository, model, pinned image, source paths and limits |
| `/etc/issuepilot/provider.env` | Model key only; readable by the service account |
| `/etc/issuepilot/service.env` | GitHub token in token mode; empty in App mode |
| `/etc/issuepilot/app.pem` | GitHub App private key in App mode |
| `/var/lib/issuepilot/` | Private durable job database and temporary source snapshots |

The service account is a member of the Docker group. This gives the trusted supervisor substantial host authority; run this on a dedicated project VPS. The model's task container never receives that group membership or the Docker socket. See `SECURITY.md`.

The wizard refuses to overwrite existing configuration. Use `sudoedit /etc/issuepilot/config.json` for later nonsecret changes. For secret rotation, edit the appropriate private file locally on the server and restart the service; do not print its content.

## 8. Verify the real Hermes runtime before publication

```bash
sudo bash deploy/admin.sh check
sudo bash deploy/admin.sh smoke-agent --provider gemini
sudo bash deploy/admin.sh smoke-agent --provider groq
```

`check` verifies read access, source paths and the local pinned image. It cannot establish model execution or GitHub comment-write permission.

`smoke-agent` spends model credit and asks **real Hermes** to read the sample files and investigate the bug. It posts nothing to GitHub. Inspect the result privately:

```bash
sudo -u issuepilot python3 -m json.tool /var/lib/issuepilot/hermes-smoke-gemini.json
```

Verify that it explains why an explicit zero becomes ten and cites the relevant source lines. Save this as your first real Hermes task evidence.

The adapter uses the official image's `/opt/hermes/.venv/bin/hermes` binary for an isolated non-root one-shot invocation, bypassing desktop/gateway initialization. This is a compatibility point that must be tested with your selected digest. If the smoke check fails, keep the service stopped; inspect the pinned image's `--help`, provider/model settings, and binary path. Never replace a failed real invocation with the demo fixture.

Two launch details are untested until this step and must be checked on your pinned image. Groq runs through Hermes's `custom` provider with `--base-url`, and the key is passed as `--api-key` by `/bin/sh` inside the container, so the image must include a shell. The `--max-turns` flag bounds tool turns. If the image rejects `--max-turns`, set `"max_turns": 0` for that provider; IssuePilot then omits the flag and reserves budget for 8 turns. `sudo bash deploy/admin.sh usage` shows what was reserved.

## 9. Start the service and prove automatic pickup

```bash
sudo systemctl enable --now issuepilot
sudo systemctl status issuepilot --no-pager
curl --fail http://127.0.0.1:8787/readyz
sudo journalctl -u issuepilot -n 40 --no-pager
```

The health endpoint binds to loopback. A successful readiness response means the worker recently discovered issues successfully; inspect durable job states separately for model/report failures.

Now use GitHub's website to create an issue:

**Title:** `A zero-percent discount changes the total`

**Body:** `Calling apply_discount(100, 0) should return 100, but it returns 90. Please investigate demo_app/discounts.py, identify the likely cause, and propose a fix and regression tests.`

Add `agent-ready`. Use your `HarshTikone` account so the default author allowlist accepts it. Then wait. **Do not run `run --once`, `smoke-agent`, or another manual agent command to handle this issue.** The already-running service must pick it up.

Expect discovery around the next 60-second poll when the queue is empty, plus model and GitHub API time. Check progress:

```bash
sudo bash deploy/admin.sh status
```

Open the automatic GitHub comment. Validate the source links, the diagnosis, the proposed tests, and its explicit static-analysis limitation. Save the issue URL and comment permalink.

## 10. Prove Linux operations and recovery

```bash
sudo systemctl restart issuepilot
curl --fail http://127.0.0.1:8787/readyz
sudo bash deploy/admin.sh status
```

Readiness may take a few seconds immediately after startup. Confirm that the completed issue receives no additional report.

Next, reboot deliberately:

```bash
sudo reboot
```

Your SSH session will disconnect. Wait for the provider to show the server running, reconnect from Windows using step 4, then run:

```bash
sudo systemctl is-enabled issuepilot
sudo systemctl is-active issuepilot
curl --fail http://127.0.0.1:8787/readyz
```

Create a second eligible issue and verify that it is handled after the reboot. Record the issue/comment URLs, checked source revision and recovery results in your private operating notes.

## Routine operation

**View current jobs:**

```bash
sudo bash /opt/issuepilot/deploy/admin.sh status
```

**Pause new work:** stop the service. An active task is allowed a bounded shutdown window to finish; if necessary systemd stops it and the cleanup command removes orphaned task containers.

```bash
sudo systemctl stop issuepilot
```

**Retry a failed/cancelled issue:** fix the underlying configuration or restore the issue's eligibility, then:

```bash
sudo systemctl stop issuepilot
sudo bash /opt/issuepilot/deploy/admin.sh retry ISSUE_NUMBER
sudo systemctl start issuepilot
```

Replace `ISSUE_NUMBER` with the actual number. Already-successful issues are not requeued by the retry command. An edited issue can be cancelled during a task; retrying it then starts a new investigation.

**Export metadata:**

```bash
sudo bash /opt/issuepilot/deploy/admin.sh export --output /var/lib/issuepilot/evidence.json
```

Inspect and redact exported files before sharing them. This export alone does not prove the live workflow: verify the external comment and your SSH deployment evidence too.

**Backup:** the `backup` command makes a consistent copy through SQLite's online backup API and checks its integrity, so the service can keep running:

```bash
sudo bash /opt/issuepilot/deploy/admin.sh backup --output /var/lib/issuepilot/backups/jobs-$(date +%F).sqlite3
```

The backup holds issue text and reports but no keys. Keep it private, encrypt it before it leaves the server, and delete old copies. To restore, stop the service, move the old `jobs.sqlite3` aside, then run `admin.sh restore PATH` and start the service. Practise this once. Keep the same GitHub identity so comment reconciliation still recognizes earlier reports.

**Monitoring:** set `heartbeat_url` to a free [Healthchecks.io](https://healthchecks.io/) check URL. The worker pings it after each cycle and pings `/fail` when GitHub polling fails or a job newly fails. Set the check's grace period above `poll_seconds + timeout_seconds`. `/readyz` also shows the oldest queued job's age and the failed-job count.

**Update or roll back:** stop the service, record the application commit and configured image digest, fetch the desired reviewed code version, run checks and the real smoke task, then start. To roll back, select the previously recorded application commit and image digest. Database schema migrations beyond this version must have an explicit backup/restore plan.

## Troubleshooting

| Symptom | Check |
|---|---|
| SSH timeout | Server running, correct IP, firewall allows your current public IP on TCP 22 |
| SSH permission denied | Right login user, private key path and public key installed on the VPS |
| GitHub 404/403 | Repository exists; token selected the correct repository; permissions and expiry |
| No issue picked up | Open issue, exact label, allowlisted author, healthy service, daily call limit |
| `RuntimeError` from model task | Real image smoke compatibility, model ID, available credit, tool capability, memory |
| `InvestigatorError:quota` or "Waiting for provider quota" | The provider returned a rate-limit error or the reserved daily budget is used; the job waits without spending an attempt. Check `usage` |
| `ContextTooLarge` | No provider accepts the snapshot; lower `retrieval_max_files` or the pinned files |
| `InvestigatorError:auth` | Wrong or revoked model key; the provider is paused for 24 hours |
| `JSONDecodeError` / `ValueError` task failure | Model output did not meet strict schema, cited invalid context or triggered credential filtering |
| `TimeoutExpired` | Provider latency, image startup behavior or resource pressure; inspect server memory and run smoke check |
| Worker already owns directory | Continuous service is running; stop it before `retry`, `run --once` or `smoke-agent` |
| Readiness fails but service is active | Recent GitHub discovery error or stale cycle; inspect service log and credentials |
| Completed comment duplicated | Inspect API ambiguity/reconciliation behavior; exactly-once external writes are not guaranteed |

Logs intentionally record error types rather than raw provider output or HTTP bodies. Diagnose on the dedicated server; do not turn raw model/credential logging on for public evidence.

When you finish experimenting, stop the service and follow the provider's billing guidance to remove resources you no longer want. Stopping the app does not by itself end VPS charges.
