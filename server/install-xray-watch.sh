#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
channel=${1:-stable}
case "$channel" in stable|preview) ;; *) echo 'Use stable or preview'; exit 1 ;; esac
test -x /usr/local/sbin/xray-maintain
test -f /etc/x-ui-maintainer.json
cat > /etc/systemd/system/xray-maintain-check.service <<EOF
[Unit]
Description=Check tested Xray candidates (never deploy)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/local/sbin/xray-maintain check --channel $channel
TimeoutStartSec=15min
EOF
cat > /etc/systemd/system/xray-maintain-check.timer <<'EOF'
[Unit]
Description=Check tested Xray candidates every six hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:55:00
RandomizedDelaySec=10min
Persistent=true
Unit=xray-maintain-check.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now xray-maintain-check.timer
echo "Enabled $channel candidate checks only. Read results: journalctl -u xray-maintain-check.service -n 50"
