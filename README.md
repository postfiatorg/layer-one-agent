# Layer-One Agent

Autonomous agent that monitors PostFiat blockchain nodes for errors and warnings via Loki, analyzes them using OpenAI, and creates pull requests with fixes in the `postfiatd` repository.

## How It Works

```
Loki (logs) → Agent (every 30 min) → OpenAI (analysis) → GitHub PR (fix)
```

1. Queries Loki for `warning`/`error`/`fatal` logs from validator, RPC, and archive nodes
2. Deduplicates and clusters log entries, then uses OpenAI to identify distinct problems
3. Compares new clusters against previously processed patterns (semantic dedup via LLM)
4. For each new problem that warrants a code fix:
   - Identifies relevant source files in `postfiatd` using module-to-directory hints
   - Generates a minimal C++ fix using OpenAI with full source file context
   - Creates a branch (`agent-{env}/{slug}`) and opens a PR assigned for review
5. For transient/benign issues, sends an email notification explaining why no PR was created

## Architecture

```
scripts/
├── docker-compose.devnet.yml    # Docker Compose for devnet
├── docker-compose.testnet.yml   # Docker Compose for testnet
├── setup-agent-server.sh        # First-time server setup
├── .env.template                # Environment variable template
└── agent/
    ├── Dockerfile
    ├── requirements.txt
    ├── crontab                  # 30-minute cron schedule
    ├── entrypoint.sh            # Container startup (clone repo, auth, start cron)
    └── src/
        ├── main.py              # Pipeline orchestrator
        ├── config.py            # Env-based configuration
        ├── models.py            # Pydantic data models
        ├── loki_client.py       # Loki HTTP API client
        ├── openai_client.py     # OpenAI Responses API wrapper
        ├── log_analyzer.py      # Log clustering + semantic dedup
        ├── code_analyzer.py     # Source file identification + fix generation
        ├── state.py             # SQLite state tracking
        ├── github_ops.py        # Git branching, commits, PR creation
        └── notifier.py          # SendGrid email notifications
```

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the complete first-time setup guide.

## Quick Start (Manual)

```bash
# On the agent server
cd /opt/agent
cp .env.template .env
# Edit .env with your secrets
docker compose -f docker-compose.testnet.yml build
docker compose -f docker-compose.testnet.yml up -d
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key with `gpt-5.2-codex` access |
| `GITHUB_TOKEN` | Yes | Fine-grained PAT with Contents + PR write access on `postfiatd` |
| `SENDGRID_API_KEY` | Yes | SendGrid API key for email notifications |
| `ENVIRONMENT` | Set by compose | `testnet` or `devnet` |
| `LOKI_URL` | Set by compose | Loki instance URL |
| `TARGET_REPO` | No | Default: `postfiatorg/postfiatd` |
| `REVIEWER` | No | Default: `DRavlic` |
| `MAX_PRS_PER_RUN` | No | Default: `3` |
| `QUERY_WINDOW_MINUTES` | No | Default: `30` |
| `NOTIFICATION_EMAIL` | No | Default: `domagoj@deltahash.net` |
