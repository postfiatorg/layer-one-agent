#!/bin/bash
set -euo pipefail

echo "=== PostFiat Layer-One Agent ==="
echo "Environment: ${ENVIRONMENT}"

# Export env vars for cron (cron does not inherit Docker env)
printenv | grep -E '^(LOKI_URL|OPENAI_API_KEY|GITHUB_TOKEN|ENVIRONMENT|TARGET_REPO|REVIEWER|MAX_PRS_PER_RUN|QUERY_WINDOW_MINUTES|SENDGRID_API_KEY|NOTIFICATION_EMAIL|GH_TOKEN|PATH)=' > /etc/environment

# Configure git identity
git config --global user.name "postfiat-agent-${ENVIRONMENT}"
git config --global user.email "layer-one-agent@deltahash.net"

# Authenticate gh CLI
echo "${GITHUB_TOKEN}" | gh auth login --with-token

# Clone postfiatd if not present
if [ ! -d "/data/postfiatd/.git" ]; then
    echo "Cloning postfiatd..."
    git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${TARGET_REPO:-postfiatorg/postfiatd}.git" /data/postfiatd
fi

# Configure remote URL with token for push access
cd /data/postfiatd
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${TARGET_REPO:-postfiatorg/postfiatd}.git"

echo "Running initial cycle..."
cd /app && python -m src.main 2>&1 | tee -a /data/agent.log

echo "Starting cron..."
cron -f
