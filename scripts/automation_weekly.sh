#!/bin/zsh
# Weekly automation: learning loop (weight tuning) + listing keep-alive renewals.
# Installed via launchd (com.etsy-engine.weekly) — see scripts/install_automation.sh
set -u
cd "$(dirname "$0")/.."
mkdir -p data/logs
{
  echo "=== weekly $(date -u +%FT%TZ) ==="
  .venv/bin/etsy-engine learn
  .venv/bin/etsy-engine renew
} >> data/logs/automation.log 2>&1
