#!/bin/zsh
# Daily automation: metrics snapshot + rank tracking.
# Installed via launchd (com.etsy-engine.daily) — see scripts/install_automation.sh
set -u
cd "$(dirname "$0")/.."
mkdir -p data/logs
{
  echo "=== daily $(date -u +%FT%TZ) ==="
  .venv/bin/etsy-engine metrics
  .venv/bin/etsy-engine rank-track
  .venv/bin/etsy-engine keyword-track
  # Publishes due Pinterest pins once direct-API auth is configured; no-ops
  # (fails soft, logged) until then.
  .venv/bin/etsy-engine pin-spread || true
} >> data/logs/automation.log 2>&1
