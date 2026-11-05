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

## 3. Rent a Linux VPS

One straightforward option is a [DigitalOcean Droplet](https://docs.digitalocean.com/products/droplets/how-to/create/). Another provider is fine if it gives you an Ubuntu server and SSH access.

Choose Ubuntu **24.04 LTS**, regular shared CPU, and a region near you. Start with **2 vCPU, 4GB RAM and at least 40GB disk** if it fits your budget. This is a starting recommendation, not a measured minimum. The model runs at an API provider, so you do not need a GPU.

Select SSH-key authentication and paste the public key from step 2. Name the server `issuepilot`. Review the recurring price before creating it and set a billing alert. Consult [current provider pricing](https://docs.digitalocean.com/products/droplets/details/pricing/); this guide does not quote a fixed plan price.

In the provider's cloud firewall, allow inbound TCP port 22 **only from your current public IP**. This project needs no other inbound app ports. If your IP changes, update the firewall source rule.

The control panel will give you an address such as `203.0.113.10`. The address here is an example; use your actual server IP.

## 4. Log in over SSH yourself

In local PowerShell:

```powershell
$issuepilotServer = "YOUR_SERVER_IP"
ssh -i "$env:USERPROFILE\.ssh\issuepilot_ed25519" "root@$issuepilotServer"
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
sudo apt-get install -y git python3 ca-certificates curl
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
sudo docker run --rm nousresearch/hermes-agent:stable --version
```

The [official Hermes Docker documentation](https://hermes-agent.nousresearch.com/docs/user-guide/docker) provides this image family. Its stable tag can change; the setup wizard records the exact downloaded digest for IssuePilot's task executions. Save the printed version and digest.

If you choose a private repository, clone using your normal GitHub SSH/deploy-key setup. Do not put a token into the clone URL or shell history. IssuePilot's separate runtime token does not need repository write access.

## 6. Create scoped runtime credentials

In GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens, create an expiring token for **only `HarshTikone/issuepilot`**:

| Repository permission | Access |
|---|---|
| Contents | Read-only |
| Issues | Read and write |
| Metadata | Read-only, automatically included |

You do not need Actions write, workflow, administration, or Contents write. This version uses a personal account identity; the comment will appear under the token owner's account. A GitHub App bot is an improvement for later. See [GitHub's token documentation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) and [comment creation permissions](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment).

Create an OpenRouter API key, configure a small spending limit in the provider account/key settings, and copy the exact ID of a tool-capable model that your account can use. The setup wizard uses OpenRouter for a concrete first path; the adapter can use another Hermes-supported API-key provider after updating configuration and the provider environment variable.

Keep both keys in your password manager while setting up. Do not paste them into this chat, issues, commits, screenshots or terminal commands.

## 7. Install and configure IssuePilot

```bash
cd /opt/issuepilot
sudo bash deploy/install-service.sh
sudo python3 deploy/configure.py
```

The wizard asks for the model ID, GitHub token and model API key. Key input is hidden and not stored in shell history. It creates:

| File | Purpose |
|---|---|
| `/etc/issuepilot/config.json` | Repository, model, pinned image, source paths and limits |
| `/etc/issuepilot/provider.env` | Model key only; readable by the service account |
| `/etc/issuepilot/service.env` | GitHub token; read by systemd as root |
| `/var/lib/issuepilot/` | Private durable job database and temporary source snapshots |

The service account is a member of the Docker group. This gives the trusted supervisor substantial host authority; run this on a dedicated project VPS. The model's task container never receives that group membership or the Docker socket. See `SECURITY.md`.

The wizard refuses to overwrite existing configuration. Use `sudoedit /etc/issuepilot/config.json` for later nonsecret changes. For secret rotation, edit the appropriate private file locally on the server and restart the service; do not print its content.

## 8. Verify the real Hermes runtime before publication

```bash
sudo bash deploy/admin.sh check
sudo bash deploy/admin.sh smoke-agent
```

`check` verifies read access, source paths and the local pinned image. It cannot establish model execution or GitHub comment-write permission.

`smoke-agent` spends model credit and asks **real Hermes** to read the sample files and investigate the bug. It posts nothing to GitHub. Inspect the result privately:

```bash
sudo -u issuepilot python3 -m json.tool /var/lib/issuepilot/hermes-smoke-report.json
```

Verify that it explains why an explicit zero becomes ten and cites the relevant source lines. Save this as your first real Hermes task evidence.

The adapter uses the official image's `/opt/hermes/.venv/bin/hermes` binary for an isolated non-root one-shot invocation, bypassing desktop/gateway initialization. This is a compatibility point that must be tested with your selected digest. If the smoke check fails, keep the service stopped; inspect the pinned image's `--help`, provider/model settings, and binary path. Never replace a failed real invocation with the demo fixture.

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

**Backup:** stop the service before copying `/var/lib/issuepilot/jobs.sqlite3` to a private backup location, then restart it. Test restores on a separate data directory. Keep the same scoped account identity for comment reconciliation.

**Update or roll back:** stop the service, record the application commit and configured image digest, fetch the desired reviewed code version, run checks and the real smoke task, then start. To roll back, select the previously recorded application commit and image digest. Database schema migrations beyond this version must have an explicit backup/restore plan.

## Troubleshooting

| Symptom | Check |
|---|---|
| SSH timeout | Server running, correct IP, firewall allows your current public IP on TCP 22 |
| SSH permission denied | Right login user, private key path and public key installed on the VPS |
| GitHub 404/403 | Repository exists; token selected the correct repository; permissions and expiry |
| No issue picked up | Open issue, exact label, allowlisted author, healthy service, daily call limit |
| `RuntimeError` from model task | Real image smoke compatibility, model ID, available credit, tool capability, memory |
| `JSONDecodeError` / `ValueError` task failure | Model output did not meet strict schema, cited invalid context or triggered credential filtering |
| `TimeoutExpired` | Provider latency, image startup behavior or resource pressure; inspect server memory and run smoke check |
| Worker already owns directory | Continuous service is running; stop it before `retry`, `run --once` or `smoke-agent` |
| Readiness fails but service is active | Recent GitHub discovery error or stale cycle; inspect service log and credentials |
| Completed comment duplicated | Inspect API ambiguity/reconciliation behavior; exactly-once external writes are not guaranteed |

Logs intentionally record error types rather than raw provider output or HTTP bodies. Diagnose on the dedicated server; do not turn raw model/credential logging on for public evidence.

When you finish experimenting, stop the service and follow the provider's billing guidance to remove resources you no longer want. Stopping the app does not by itself end VPS charges.
