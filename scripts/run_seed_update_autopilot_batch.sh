#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
UV="/home/linuxbrew/.linuxbrew/bin/uv"
SUMMARY="$ROOT/logs/evals/seed_update_autopilot/current/seed_update_autopilot_summary.json"
LOCK="$ROOT/logs/evals/seed_update_autopilot/overnight_batch.lock"
LOG="$ROOT/logs/evals/seed_update_autopilot/overnight_batch.log"

mkdir -p "$(dirname -- "$LOG")"

if [ ! -f "$SUMMARY" ] || ! jq -e '.success == true and .finished_at != null' "$SUMMARY" >/dev/null 2>&1; then
  exit 0
fi

if ! mkdir "$LOCK" 2>/dev/null; then
  exit 0
fi

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    rmdir "$LOCK" 2>/dev/null || true
  fi
}
trap cleanup EXIT

{
  printf '[%s] launching overnight batch\n' "$(date -Iseconds)"
  cd "$ROOT"
  set +e
  "$UV" run dataset/evals/eval_seed_update_autopilot_per_seed.py --author --seed-workers 4 --limit 30 --author-retries 2 --queue
  status=$?
  set -e
  printf '[%s] overnight batch finished with exit %s\n' "$(date -Iseconds)" "$status"
  exit "$status"
} >> "$LOG" 2>&1
