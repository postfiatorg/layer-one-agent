# Deployment Guide

Complete first-time setup guide for the PostFiat Layer-One Agent.

## Prerequisites

- Two VPS instances (one per environment): Ubuntu 22.04+, 2GB+ RAM, 20GB+ storage each
  - Testnet: dedicated server
  - Devnet: dedicated server
- Loki instance running at `infra-monitoring.<env>.postfiat.org:3100`
- Admin access to the `postfiatorg` GitHub organization

## 1. GitHub Machine User

Create a dedicated GitHub account for the agent:

1. Sign up at https://github.com/signup with a dedicated email
2. Username: `postfiat-agent` (or similar)
3. Verify the email address

## 2. Organization Membership and Repository Access

The machine user must be an organization member before it can create a fine-grained PAT scoped to `postfiatorg`.

From an admin account on `postfiatorg`:

1. Go to `github.com/orgs/postfiatorg/people` → **Invite member**
2. Add the machine user with **Member** role
3. Accept the invitation from the machine user account
4. Go to `postfiatorg/postfiatd` → **Settings → Collaborators**
5. Add the machine user as a collaborator with **Write** role

## 3. GitHub Personal Access Token

Generate a fine-grained PAT from the machine user account:

1. Go to **Settings → Developer settings → Fine-grained personal access tokens**
2. Click **Generate new token**
3. Token name: `layer-one-agent`
4. Resource owner: `postfiatorg`
5. Repository access: **Only select repositories** → `postfiatd`
6. Permissions:
   - **Contents**: Read and write
   - **Pull requests**: Read and write
   - **Metadata**: Read-only (granted by default)
7. Generate and save the token

## 4. Branch Protection Rules

Protect the `main`, `testnet`, and `devnet` branches so the agent cannot push directly to them. Repeat the steps below for each branch.

From your admin account, go to `postfiatorg/postfiatd` → **Settings → Branches**:

1. Click **Add branch protection rule** (or **Add rule** under "Branch protection rules")
2. **Branch name pattern**: enter the branch name (e.g. `main`)
3. Enable the following settings:
   - **Require a pull request before merging**: check this box
     - **Required number of approvals before merging**: set to `1`
     - **Dismiss stale pull request approvals when new commits are pushed**: check this box
   - **Require status checks to pass before merging**: optional, enable if you have CI
   - **Do not allow bypassing the above settings**: check this box (prevents even admins from bypassing)
4. Leave all other settings at their defaults
5. Click **Create** (or **Save changes**)
6. Repeat for `testnet` and `devnet`

The agent pushes only to `agent-testnet/*` and `agent-devnet/*` branches (which are not protected), then opens a PR targeting `main`. All merges to protected branches require a reviewed PR.

## 5. OpenAI API Key

1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Verify access to `gpt-5.2-codex`
4. Set a monthly spend limit (recommended: $50–100/month to start)

## 6. Resend Setup

1. Create a Resend account at https://resend.com
2. Go to **API Keys → Create API Key**
3. Add and verify your sending domain (`postfiat.org`)
4. The agent sends from `agent-{environment}@postfiat.org`

## 7. Server Setup

Provision a VPS, then run the setup script:

```bash
ssh root@<server-ip>
curl -fsSL https://raw.githubusercontent.com/postfiatorg/layer-one-agent/main/scripts/setup-agent-server.sh | bash
```

Or manually:

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker

# Install Docker Compose plugin
apt-get update && apt-get install -y docker-compose-plugin

# Create agent directory
mkdir -p /opt/agent

# Configure firewall (SSH only — agent makes outbound connections only)
ufw allow 22/tcp
ufw --force enable
```

## 8. Configure Secrets

Create the `.env` file on the server:

```bash
cat > /opt/agent/.env << 'EOF'
OPENAI_API_KEY=sk-...
GITHUB_TOKEN=github_pat_...
RESEND_API_KEY=re_...
NOTIFICATION_EMAIL=domagoj@deltahash.net
REVIEWER=DRavlic
TARGET_REPO=postfiatorg/postfiatd
EOF

chmod 600 /opt/agent/.env
```

## 9. SSH Deploy Key for CI/CD

If you already configured an SSH key pair during VPS provisioning (e.g. via Vultr), you can reuse it. Otherwise, generate a new one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/layer-one-agent -C "layer-one-agent-deploy" -N ""
ssh-copy-id -i ~/.ssh/layer-one-agent.pub root@<server-ip>
```

Add GitHub Actions secrets in the `layer-one-agent` repo (**Settings → Secrets and variables → Actions**):

| Secret | Value |
|---|---|
| `TESTNET_HOST` | Server IP/hostname for testnet |
| `TESTNET_SSH_KEY` | Private key that has SSH access to the testnet server |
| `DEVNET_HOST` | Server IP/hostname for devnet (separate server) |
| `DEVNET_SSH_KEY` | Private key that has SSH access to the devnet server |

## 10. Deploy via CI/CD

Push to the `testnet` or `devnet` branch:

```bash
git checkout -b testnet
git push -u origin testnet
```

The workflow will:
1. SCP `scripts/` to the server
2. `rsync` to `/opt/agent/`
3. `docker compose build`
4. `docker compose up -d --force-recreate`
5. Verify the container is running

## 11. Deploy Manually

As an alternative to CI/CD:

```bash
# On your local machine
scp -r scripts/* root@<server-ip>:/opt/agent/

# On the server
cd /opt/agent
docker compose -f docker-compose.testnet.yml build
docker compose -f docker-compose.testnet.yml up -d
```

## 12. Verify Deployment

```bash
# Check container is running
docker ps --filter "name=layer-one-agent"

# Check agent logs
docker logs layer-one-agent --tail 50

# Check cron is scheduled
docker exec layer-one-agent crontab -l

# Force a manual run
docker exec layer-one-agent python -m src.main
```

## 13. Monitoring

### Container status

```bash
# Is the agent running?
docker ps --filter "name=layer-one-agent" --format "table {{.Status}}\t{{.Image}}\t{{.CreatedAt}}"

# Container resource usage
docker stats layer-one-agent --no-stream
```

### Agent logs

```bash
# Live logs (entrypoint + cron output)
docker logs layer-one-agent --follow --tail 100

# Last run output only
docker exec layer-one-agent tail -200 /data/agent.log

# Search for errors in logs
docker exec layer-one-agent grep -i "error\|fatal\|traceback" /data/agent.log | tail -30
```

### Cron schedule

```bash
# Verify cron is registered
docker exec layer-one-agent crontab -l

# Check when cron last ran
docker exec layer-one-agent ls -la /data/agent.log
```

### State database

```bash
# Recent runs (last 10)
docker exec layer-one-agent sqlite3 -header -column /data/state.db \
  "SELECT id, datetime(started_at, 'unixepoch') AS started, clusters_found, prs_created, errors, round(duration_seconds,1) AS duration_s FROM runs ORDER BY id DESC LIMIT 10;"

# All processed patterns
docker exec layer-one-agent sqlite3 -header -column /data/state.db \
  "SELECT slug, status, pr_url, datetime(created_at, 'unixepoch') AS created FROM processed_patterns ORDER BY created_at DESC;"

# Log snapshots from last run
docker exec layer-one-agent sqlite3 -header -column /data/state.db \
  "SELECT cluster_slug, module, severity, occurrence_count FROM log_snapshots WHERE run_id = (SELECT MAX(id) FROM runs);"
```

### Quick health check

```bash
# All-in-one: container status, last run, and recent errors
docker ps --filter "name=layer-one-agent" --format "Container: {{.Status}}" && \
docker exec layer-one-agent sqlite3 /data/state.db \
  "SELECT 'Last run: ' || datetime(started_at, 'unixepoch') || ' | clusters=' || clusters_found || ' prs=' || prs_created || ' errors=' || errors FROM runs ORDER BY id DESC LIMIT 1;" && \
docker exec layer-one-agent grep -c "ERROR\|CRITICAL" /data/agent.log 2>/dev/null | xargs -I{} echo "Error lines in log: {}"
```

## 14. Maintenance

### Rotate API keys

Update `/opt/agent/.env` on the server, then restart:

```bash
docker compose -f docker-compose.testnet.yml up -d --force-recreate
```

### Clear state to re-process patterns

```bash
docker exec layer-one-agent sqlite3 /data/state.db "DELETE FROM processed_patterns;"
```

### Force a run

```bash
docker exec layer-one-agent python -m src.main
```

### Prune old agent branches in postfiatd

```bash
git ls-remote --heads origin 'agent-*' | awk '{print $2}' | sed 's|refs/heads/||'
# Delete selectively:
git push origin --delete agent-testnet/some-old-slug
```

## 15. Troubleshooting

**Agent not creating PRs**
- Check Loki connectivity: `curl http://infra-monitoring.testnet.postfiat.org:3100/ready`
- Check token permissions: `docker exec layer-one-agent gh auth status`
- Check logs: `docker logs layer-one-agent --tail 100`

**OpenAI API errors**
- Verify key: check `OPENAI_API_KEY` in `.env`
- Check model access: ensure `gpt-5.2-codex` is available on your account
- Rate limits: check OpenAI dashboard for usage

**Duplicate PRs**
- Inspect state: `docker exec layer-one-agent sqlite3 /data/state.db "SELECT slug, pr_url FROM processed_patterns;"`
- The agent also checks for existing branches/PRs as a safety net

**Resend not sending**
- Verify domain is configured in Resend dashboard
- Check API key is valid: `curl -s -H "Authorization: Bearer $RESEND_API_KEY" https://api.resend.com/domains`

**Container not starting**
- Check env vars: `docker compose config`
- Check build: `docker compose build --no-cache`
- Check Docker logs: `docker logs layer-one-agent`
