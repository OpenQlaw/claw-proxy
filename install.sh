#!/usr/bin/env bash
# install.sh — Set up claw-proxy as a systemd user service (Linux/WSL2)
# Run as the agent user, not root.
set -euo pipefail

PROXY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.config/claw-proxy"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/claw-proxy.service"
VENV_DIR="$PROXY_DIR/.venv"
PORT="${CLAW_PROXY_PORT:-8020}"

echo "[claw-proxy] Installing from: $PROXY_DIR"

# --- Create config dir and initial quota state if absent ---
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/quota-state.json" ]]; then
    RESET_DATE=$(date -d "$(date +%Y-%m-01) +1 month" +%Y-%m-%d 2>/dev/null || \
                 python3 -c "import datetime; d=datetime.date.today().replace(day=1); \
                   import calendar; print(d.replace(month=d.month%12+1, \
                   year=d.year+(1 if d.month==12 else 0)).isoformat())")
    cat > "$CONFIG_DIR/quota-state.json" <<EOF
{
  "copilot": {
    "monthly_limit": 1000,
    "used_this_month": 0,
    "reset_date": "${RESET_DATE}",
    "last_updated": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  },
  "claude_cli": {
    "window_tokens": 200000,
    "used_this_window": 0,
    "window_start": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "window_hours": 5
  },
  "default_backend": "copilot",
  "force_local_patterns": [
    "password", "secret", "vault", "credential",
    "token", "ssh_key", "api_key", "passphrase"
  ]
}
EOF
    echo "[claw-proxy] Created initial quota-state.json at $CONFIG_DIR/quota-state.json"
fi

# --- Python venv ---
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$PROXY_DIR/requirements.txt"
echo "[claw-proxy] Python venv ready at $VENV_DIR"

# --- Systemd user service ---
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=claw-proxy — quota-aware OpenAI-compatible gateway
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROXY_DIR}
ExecStart=${VENV_DIR}/bin/uvicorn main:app --host 127.0.0.1 --port ${PORT} --log-level warning
Restart=on-failure
RestartSec=5
# Security hardening
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${CONFIG_DIR} ${PROXY_DIR}

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now claw-proxy.service
echo "[claw-proxy] Service enabled and started on port ${PORT}"
echo "[claw-proxy] Check status: systemctl --user status claw-proxy"
echo "[claw-proxy] Quota status: curl http://127.0.0.1:${PORT}/quota"
echo "[claw-proxy] Health:       curl http://127.0.0.1:${PORT}/health"
