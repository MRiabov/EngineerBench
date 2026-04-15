#!/bin/bash
# scripts/env_up.sh
# Sets up the Problemologist-AI development environment using local infra,
# local FastAPI servers, and the containerized renderer.
# Use this for local debugging, optimization, or manual testing.

set -e

# Ensure we are in project root
cd "$(dirname "$0")/.."

STACK_PROFILE="${PROBLEMOLOGIST_STACK_PROFILE:-integration}"
FORCE_RUN_ALEMBIC=0
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
    --force-run-alembic)
      FORCE_RUN_ALEMBIC=1
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
  if [ "${PROBLEMOLOGIST_EVAL_LOCK_QUEUE:-0}" = "1" ]; then
    echo "[eval-env-lock] Waiting for eval lock at $EVAL_RUN_LOCK_PATH..."
    flock 9
  elif ! flock -n 9; then
    echo "Be careful - another eval run is already running." >&2
    echo "Your requested command: [scripts/env_up.sh --profile eval]" >&2
    echo "If you only need validation, rerun that check with --skip-env-up so it can join the shared validation lock." >&2
    echo "If you want to wait for the shared lock, rerun via the eval runner with --queue." >&2
    exit 1
  fi
  export PROBLEMOLOGIST_EVAL_LOCK_HELD=1
fi

# Networking for local services (infra is still in Docker but exposed on host).
# Default to real/manual mode unless explicitly overridden by caller.
export IS_INTEGRATION_TEST="${IS_INTEGRATION_TEST:-false}"
export LOG_LEVEL=${LOG_LEVEL:-INFO}
export PYTHONUNBUFFERED=1

# Load .env if it exists to pick up API keys (OpenAI, etc.)
if [ -f .env ]; then
  echo "Loading environment from .env..."
  while IFS= read -r line || [ -n "$line" ]; do
    line=$(echo "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    [[ "$line" =~ ^#.*$ ]] && continue
    [[ -z "$line" ]] && continue
    if [[ "$line" == *#* ]]; then
      if [[ "$line" != *\"*#*\"* && "$line" != *\'*#*\'* ]]; then
        line="${line%%#*}"
      fi
    fi
    clean_line=$(echo "$line" | sed -E 's/[[:space:]]*=[[:space:]]*/=/')
    if [[ "$clean_line" =~ ^[A-Za-z_][A-Za-z0-9_]*=.*$ ]]; then
      clean_line=$(echo "$clean_line" | sed -e 's/[[:space:]]*$//')
      key="${clean_line%%=*}"
      value="${clean_line#*=}"
      # If the value is wrapped in matching quotes, strip one layer so env vars
      # contain the raw value (e.g. https://... instead of \"https://...\").
      if [[ "$value" =~ ^\".*\"$ ]]; then
        value="${value:1:-1}"
      elif [[ "$value" =~ ^\'.*\'$ ]]; then
        value="${value:1:-1}"
      fi
      export "$key=$value"
    fi
  done < .env
fi

eval "$(python3 -m evals.logic.stack_profiles --profile "$STACK_PROFILE" --root "$(pwd)" --format shell)"

export LOG_DIR="${LOG_DIR:-$STACK_DEFAULT_LOG_DIR}"
export ARCHIVE_DIR="${ARCHIVE_DIR:-$STACK_DEFAULT_ARCHIVE_DIR}"
export WORKER_SESSIONS_DIR="${WORKER_SESSIONS_DIR:-$STACK_DEFAULT_WORKER_SESSIONS_DIR}"
mkdir -p "$WORKER_SESSIONS_DIR"
mkdir -p "$STACK_STATE_DIR"
mkdir -p "$STACK_PID_DIR"

# Stop any existing environment for the selected profile first to ensure a
# clean start without touching the other profile's stack.
./scripts/env_down.sh --profile "$STACK_PROFILE"

# Ensure Docker is working correctly (fix for sandboxed environments / Docker-in-Docker).
# DO NOT REMOVE: This is required for agent execution environments where overlay2 fails.
bash scripts/ensure_docker_vfs.sh

echo "Spinning up infrastructure (Postgres, Minio)..."
docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.test.yaml up -d --remove-orphans

echo "Waiting for infra to be ready..."
MAX_INFRA_RETRIES=60

# Wait for Postgres
INFRA_COUNT=0
until docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.test.yaml exec postgres pg_isready -U postgres > /dev/null 2>&1 || [ $INFRA_COUNT -eq $MAX_INFRA_RETRIES ]; do
  echo "Waiting for Postgres... ($INFRA_COUNT/$MAX_INFRA_RETRIES)"
  sleep 2
  INFRA_COUNT=$((INFRA_COUNT + 1))
done

# Wait for Minio
INFRA_COUNT=0
until curl -s "http://127.0.0.1:${MINIO_HOST_PORT}/minio/health/live" > /dev/null 2>&1 || [ $INFRA_COUNT -eq $MAX_INFRA_RETRIES ]; do
  echo "Waiting for Minio... ($INFRA_COUNT/$MAX_INFRA_RETRIES)"
  sleep 2
  INFRA_COUNT=$((INFRA_COUNT + 1))
done

echo "Purging local S3 buckets before the run..."
uv run python scripts/cleanup_local_s3.py

MIGRATION_ARGS=()
if [ "$FORCE_RUN_ALEMBIC" = "1" ]; then
  echo "Force-running migrations..."
  MIGRATION_ARGS=(--force-run-alembic)
else
  echo "Checking whether migrations are needed..."
fi
uv run python scripts/internal/integration_runner.py migrate "${MIGRATION_ARGS[@]}"

echo "Starting Application Servers..."

# Ensure log directory exists and manage log history
SKIP_LOG_ARCHIVE="${SKIP_LOG_ARCHIVE:-0}"
mkdir -p "$LOG_DIR"
mkdir -p "$ARCHIVE_DIR"

# Archive previous logs if they exist
if [ "$SKIP_LOG_ARCHIVE" != "1" ] && [ -d "$LOG_DIR" ] && [ "$(ls -A "$LOG_DIR")" ]; then
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  mv "$LOG_DIR" "$ARCHIVE_DIR/run_${TIMESTAMP}"
  mkdir -p "$LOG_DIR"
fi

# Clean up archives older than 24 hours
find "$ARCHIVE_DIR" -maxdepth 1 -name "run_*" -mmin +1440 -exec rm -rf {} + 2>/dev/null || true

start_detached_service() {
  local log_path="$1"
  shift
  # Close fd 9 in the child before exec so the eval lock stays owned by this
  # launcher shell instead of leaking into long-lived service processes.
  setsid bash -lc 'exec 9>&-; exec "$@"' _ "$@" > "$log_path" 2>&1 &
  echo $!
}

# Start Worker Light (port 18001)
export PYTHONPATH=$PYTHONPATH:.
export WORKER_TYPE=light
export EXTRA_DEBUG_LOG="$LOG_DIR/worker_light_debug.log"
WORKER_LIGHT_PID=$(start_detached_service "$LOG_DIR/worker_light.log" .venv/bin/python -m uvicorn worker_light.app:app --host 0.0.0.0 --port "$WORKER_LIGHT_HOST_PORT")
echo $WORKER_LIGHT_PID > "$STACK_PID_DIR/worker_light.pid"
echo "Worker Light started (PID: $WORKER_LIGHT_PID)"

# Start Worker Renderer in Docker (port 18003)
export WORKER_RENDERER_LOG_DIR="$LOG_DIR"
WORKER_RENDERER_COMPOSE_CMD=(docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml)
if ! docker image inspect problemologist-ai-worker-renderer:latest >/dev/null 2>&1; then
  echo "Building Worker Renderer image..."
  docker build -f worker_renderer/Dockerfile -t problemologist-ai-worker-renderer:latest .
fi
echo "Starting Worker Renderer container..."
"${WORKER_RENDERER_COMPOSE_CMD[@]}" up -d --no-deps worker-renderer > "$LOG_DIR/worker_renderer.log" 2>&1
WORKER_RENDERER_CONTAINER_ID=$("${WORKER_RENDERER_COMPOSE_CMD[@]}" ps -q worker-renderer | tr -d '\r')
if [ -z "$WORKER_RENDERER_CONTAINER_ID" ]; then
  echo "Failed to resolve Worker Renderer container id."
  exit 1
fi
echo "$WORKER_RENDERER_CONTAINER_ID" > "$STACK_PID_DIR/worker_renderer.pid"
echo "Worker Renderer container started (ID: $WORKER_RENDERER_CONTAINER_ID)"

# Start Worker Heavy (port 18002)
export WORKER_TYPE=heavy
export EXTRA_DEBUG_LOG="$LOG_DIR/worker_heavy_debug.log"
WORKER_HEAVY_PID=$(start_detached_service "$LOG_DIR/worker_heavy.log" .venv/bin/python -m uvicorn worker_heavy.app:app --host 0.0.0.0 --port "$WORKER_HEAVY_HOST_PORT")
echo $WORKER_HEAVY_PID > "$STACK_PID_DIR/worker_heavy.pid"
echo "Worker Heavy started (PID: $WORKER_HEAVY_PID)"

# Start Controller (port 18000)
export EXTRA_DEBUG_LOG="$LOG_DIR/controller_debug.log"
CONTROLLER_PID=$(start_detached_service "$LOG_DIR/controller.log" .venv/bin/python -m uvicorn controller.api.main:app --host 0.0.0.0 --port "$CONTROLLER_HOST_PORT")
echo $CONTROLLER_PID > "$STACK_PID_DIR/controller.pid"
echo "Controller started (PID: $CONTROLLER_PID)"

# Start Frontend dev server if default port is available
FRONTEND_PORT="$FRONTEND_HOST_PORT"
FRONTEND_STARTED=false
if [ "$STACK_START_FRONTEND" = "1" ] && python3 - "$FRONTEND_PORT" <<'PY'
import socket, sys
port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(0.2)
    sys.exit(0 if s.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
then
  echo "Frontend port ${FRONTEND_PORT} is already in use; skipping npm dev server startup."
elif [ "$STACK_START_FRONTEND" = "1" ]; then
  echo "Starting Frontend dev server on port ${FRONTEND_PORT}..."
  (
    cd frontend
    FRONTEND_PID=$(start_detached_service "../$LOG_DIR/frontend.log" npm run dev)
    echo "$FRONTEND_PID" > "$STACK_PID_DIR/frontend.pid"
  )
  FRONTEND_STARTED=true
  echo "Frontend dev server started (PID: $(cat "$STACK_PID_DIR/frontend.pid"))"
else
  echo "Skipping Frontend dev server startup for profile '$STACK_PROFILE'."
fi

if [ "$STACK_CREATE_ROOT_LOG_SYMLINKS" = "1" ] && [ "${LOG_DIR#logs/}" != "$LOG_DIR" ]; then
  # Create convenience symlinks in the logs/ root for the integration profile.
  # We strip the logs/ prefix from LOG_DIR to get the relative target.
  REL_LOG_DIR="${LOG_DIR#logs/}"
  ln -sf "$REL_LOG_DIR/controller.log" logs/controller.log
  ln -sf "$REL_LOG_DIR/controller_debug.log" logs/controller_debug.log
  ln -sf "$REL_LOG_DIR/worker_light.log" logs/worker_light.log
  ln -sf "$REL_LOG_DIR/worker_light_debug.log" logs/worker_light_debug.log
  ln -sf "$REL_LOG_DIR/worker_renderer.log" logs/worker_renderer.log
  ln -sf "$REL_LOG_DIR/worker_renderer_debug.log" logs/worker_renderer_debug.log
  ln -sf "$REL_LOG_DIR/worker_heavy.log" logs/worker_heavy.log
  ln -sf "$REL_LOG_DIR/worker_heavy_debug.log" logs/worker_heavy_debug.log
  ln -sf "$REL_LOG_DIR/frontend.log" logs/frontend.log
fi

echo "Waiting for services to be healthy..."
sleep 2

wait_for_health() {
  local name="$1"
  local url="$2"
  local retries="${3:-30}"
  local delay="${4:-1}"
  local i=0

  while [ "$i" -lt "$retries" ]; do
  if curl -s "$url" | grep -q "healthy"; then
      echo "$name is healthy!"
      return 0
    fi
    i=$((i + 1))
    sleep "$delay"
  done

  echo "$name health check failed after ${retries}s (see logs in $LOG_DIR)"
  return 1
}

check_runtime_alive() {
  local name="$1"
  local runtime_id="$2"
  if [ -z "$runtime_id" ]; then
    echo "$name runtime id is empty"
    return 1
  fi
  if [[ "$runtime_id" =~ ^[0-9]+$ ]]; then
    if kill -0 "$runtime_id" 2>/dev/null; then
      return 0
    fi
  elif docker inspect -f '{{.State.Running}}' "$runtime_id" 2>/dev/null | grep -q '^true$'; then
    return 0
  fi
  echo "$name runtime is not running (ID: $runtime_id)"
  return 1
}

FAIL=0

check_runtime_alive "Worker Light" "$WORKER_LIGHT_PID" || FAIL=1
check_runtime_alive "Worker Renderer" "$WORKER_RENDERER_CONTAINER_ID" || FAIL=1
check_runtime_alive "Worker Heavy" "$WORKER_HEAVY_PID" || FAIL=1
check_runtime_alive "Controller" "$CONTROLLER_PID" || FAIL=1

wait_for_health "Worker Light" "http://127.0.0.1:${WORKER_LIGHT_HOST_PORT}/health" || FAIL=1
wait_for_health "Worker Renderer" "http://127.0.0.1:${WORKER_RENDERER_HOST_PORT}/health" || FAIL=1
wait_for_health "Worker Heavy" "http://127.0.0.1:${WORKER_HEAVY_HOST_PORT}/health" || FAIL=1
wait_for_health "Controller" "http://127.0.0.1:${CONTROLLER_HOST_PORT}/api/health" || FAIL=1

if [ "$FRONTEND_STARTED" = true ]; then
  sleep 2
  if curl -sf "http://127.0.0.1:${FRONTEND_PORT}" > /dev/null 2>&1; then
    echo "Frontend is healthy on http://127.0.0.1:${FRONTEND_PORT}!"
  else
    echo "Frontend health check failed (see logs in $LOG_DIR/frontend.log)"
  fi
fi

if [ "$FAIL" -ne 0 ]; then
  echo "Environment startup failed."
  exit 1
fi

echo "Environment is UP for profile '$STACK_PROFILE'. Use 'scripts/env_down.sh --profile $STACK_PROFILE' to stop."
echo "Mode: IS_INTEGRATION_TEST=$IS_INTEGRATION_TEST"
