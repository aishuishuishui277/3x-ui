#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
test "$(uname -m)" = x86_64
for tool in python3 curl systemctl; do command -v "$tool" >/dev/null; done
python3 -c 'import sys,tarfile; assert sys.version_info >= (3, 11) and hasattr(tarfile,"data_filter"), "Current Python 3.11+ security updates required"'
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -m 0755 "$here/xui-maintain.py" /usr/local/sbin/xui-maintain
install -m 0755 "$here/xray-maintain.py" /usr/local/sbin/xray-maintain
install -d -m 0700 /var/lib/x-ui-maintainer
echo 'Installed updater only. Next: sudo xui-maintain init --health-url http://127.0.0.1:2053/YOUR_BASE_PATH/'
