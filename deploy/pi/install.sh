#!/usr/bin/env bash
# Install Ghost Job Tracker as a scheduled service on a Raspberry Pi (or any systemd Linux).
#
#   bash deploy/pi/install.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/../.." && pwd)"
USER_NAME="$(id -un)"

cd "$DIR"

# 1. uv (manages Python 3.12 for us - Pi OS ships an older Python)
if ! command -v uv >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/uv" ]]; then
    echo "==> Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

# 2. Dependencies
echo "==> Installing dependencies"
"$UV" sync --no-dev

# 3. Config
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo
    echo "!! Created .env - add NTFY_TOPIC (and REED_API_KEY if you have it),"
    echo "   then re-run this script. You can add the Reed key later."
    exit 1
fi

# 4. Sanity check: one run now, so problems show up here not in the logs.
#    Without an API key yet this just warns - the schedule still gets installed.
echo "==> Test run"
"$UV" run --no-sync ghostjobs run
"$UV" run --no-sync ghostjobs status

# 5. systemd units
echo "==> Installing systemd units"
render() {
    sed -e "s|__USER__|$USER_NAME|g" -e "s|__DIR__|$DIR|g" -e "s|__UV__|$UV|g" "$1"
}
render deploy/pi/ghostjobs.service | sudo tee /etc/systemd/system/ghostjobs.service >/dev/null
sudo cp deploy/pi/ghostjobs.timer /etc/systemd/system/ghostjobs.timer

sudo systemctl daemon-reload
sudo systemctl enable --now ghostjobs.timer

echo
echo "Done. Next runs:"
systemctl list-timers ghostjobs.timer --no-pager
echo "Logs:      journalctl -u ghostjobs -e"
