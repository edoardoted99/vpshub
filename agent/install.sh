#!/bin/bash
# ServerCrown Agent installer
# Usage: curl -s http://yourserver/install.sh | bash -s -- <SERVER_URL> <TOKEN>

set -e

SERVER_URL="${1:?Usage: install.sh <SERVER_URL> <TOKEN>}"
TOKEN="${2:?Usage: install.sh <SERVER_URL> <TOKEN>}"
INSTALL_DIR="/opt/servercrown-agent"

echo "[*] Installing ServerCrown Agent..."

# Install dependencies
if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv > /dev/null
elif command -v yum &>/dev/null; then
    yum install -y -q python3 python3-pip > /dev/null
fi

# Create install dir
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Create venv and install deps
python3 -m venv venv
./venv/bin/pip install --quiet psutil websockets

# Copy agent script
cat > agent.py << 'AGENT_EOF'
AGENT_EOF

# We'll download the agent from the server in production.
# For now, copy it manually or use scp.
echo "[*] Place agent.py in $INSTALL_DIR"

# Create systemd service
cat > /etc/systemd/system/servercrown-agent.service << EOF
[Unit]
Description=ServerCrown Agent
After=network.target

[Service]
Type=simple
Environment=CROWN_SERVER_URL=${SERVER_URL}
Environment=CROWN_TOKEN=${TOKEN}
Environment=CROWN_INTERVAL=10
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable servercrown-agent
systemctl start servercrown-agent

echo "[*] ServerCrown Agent installed and running!"
echo "[*] Check status: systemctl status servercrown-agent"
