#!/bin/bash
set -euo pipefail

echo "=== PostFiat Agent Server Setup ==="

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Install docker compose plugin if not present
if ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose plugin..."
    apt-get update
    apt-get install -y docker-compose-plugin
fi

# Create agent directory
AGENT_DIR="/opt/agent"
echo "Creating ${AGENT_DIR}..."
mkdir -p "${AGENT_DIR}"

# Configure firewall (ufw) — agent only needs SSH (outbound connections only)
if command -v ufw &> /dev/null; then
    echo "Configuring firewall..."
    ufw allow 22/tcp
    ufw --force enable
fi

echo ""
echo "=========================================="
echo "  Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Create /opt/agent/.env with your secrets"
echo "  2. Deploy via CI/CD or manually"
echo ""
echo "See: docs/DEPLOYMENT.md"
echo ""
