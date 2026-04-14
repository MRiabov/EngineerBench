#!/bin/bash
# scripts/env_down.sh
# Stops the Problemologist-AI development environment.

set -e

# Ensure we are in project root
cd "$(dirname "$0")/.."

STACK_PROFILE="${PROBLEMOLOGIST_STACK_PROFILE:-integration}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --profile"
        exit 1
      fi
      STACK_PROFILE="$2"
      shift 2
      ;;
    --profile=*)
      STACK_PROFILE="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done
export PROBLEMOLOGIST_STACK_PROFILE="$STACK_PROFILE"

EVAL_RUN_FAMILY="${PROBLEMOLOGIST_EVAL_FAMILY:-eval}"
EVAL_RUN_ROOT="${EVAL_RUN_ROOT:-/tmp/problemologist-evals/$EVAL_RUN_FAMILY}"
EVAL_RUN_LOCK_PATH="${EVAL_RUN_LOCK_PATH:-$EVAL_RUN_ROOT/problemologist-eval.lock}"
mkdir -p "$EVAL_RUN_ROOT"
if [ "$STACK_PROFILE" = "eval" ] && [ "${PROBLEMOLOGIST_EVAL_LOCK_HELD:-0}" != "1" ]; then
  exec 9>"$EVAL_RUN_LOCK_PATH"
  if ! flock -n 9; then
    echo "Be careful - another eval run is already running." >&2
    echo "Your requested command: [scripts/env_down.sh --profile eval]" >&2
    echo "If you only need validation, rerun that check with --skip-env-up so it can join the shared validation lock." >&2
    echo "If you want to wait for the shared lock, rerun via the eval runner with --queue." >&2
    exit 1
  fi
  export PROBLEMOLOGIST_EVAL_LOCK_HELD=1
fi

eval "$(python3 -m evals.logic.stack_profiles --profile "$STACK_PROFILE" --root "$(pwd)" --format shell)"

echo "Stopping Application Servers..."

stop_pid_file() {
  local label="$1"
  local pid_file="$2"
  if [ -f "$pid_file" ]; then
    PID=$(cat "$pid_file" | tr -d '\r\n')
    if [ -n "$PID" ]; then
      if [[ "$PID" =~ ^[0-9]+$ ]]; then
        echo "Stopping ${label} (PID: $PID)..."
        kill "$PID" 2>/dev/null || true
      else
        echo "Stopping ${label} container (ID: $PID)..."
        docker stop "$PID" 2>/dev/null || true
      fi
    fi
    rm -f "$pid_file"
  fi
}

stop_pid_file "Worker Light" "$STACK_PID_DIR/worker_light.pid"
stop_pid_file "Worker Renderer" "$STACK_PID_DIR/worker_renderer.pid"
stop_pid_file "Worker Heavy" "$STACK_PID_DIR/worker_heavy.pid"
stop_pid_file "Controller" "$STACK_PID_DIR/controller.pid"
stop_pid_file "Frontend dev server" "$STACK_PID_DIR/frontend.pid"

docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml stop worker-renderer >/dev/null 2>&1 || true

if [ "$STACK_CREATE_ROOT_LOG_SYMLINKS" = "1" ]; then
  rm -f \
    logs/controller.log \
    logs/controller_debug.log \
    logs/worker_light.log \
    logs/worker_light_debug.log \
    logs/worker_renderer.log \
    logs/worker_renderer_debug.log \
    logs/worker_heavy.log \
    logs/worker_heavy_debug.log \
    logs/frontend.log
fi

echo "Bringing down infrastructure containers..."
docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.test.yaml down -v --remove-orphans

echo "Environment is DOWN."
