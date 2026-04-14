#!/bin/sh
set -eu

# Thin wrapper around the Python submission helper.
# The shell script is the agent-facing command surface; Python does the validation.
PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python 2>/dev/null || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "Error: unable to locate python3 or python on PATH" >&2
  exit 127
fi

PROBLEMOLOGIST_REPO_ROOT="${PROBLEMOLOGIST_REPO_ROOT:-}"
if [ -n "$PROBLEMOLOGIST_REPO_ROOT" ]; then
  if [ -n "${PYTHONPATH:-}" ]; then
    export PYTHONPATH="$PROBLEMOLOGIST_REPO_ROOT:$PYTHONPATH"
  else
    export PYTHONPATH="$PROBLEMOLOGIST_REPO_ROOT"
  fi
fi

export XDG_CACHE_HOME="$PWD/.codex-cache"
export XDG_CONFIG_HOME="$PWD/.codex-config"
export TMPDIR="$PWD/.codex-tmp"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
unset DISPLAY
unset XAUTHORITY
unset WAYLAND_DISPLAY
export PROBLEMOLOGIST_PHYSICS_GL_BACKEND=egl
export PROBLEMOLOGIST_RENDER_GL_BACKEND=osmesa
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=osmesa
export PYVISTA_OFF_SCREEN=true
export VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow
export PYGLET_HEADLESS=1
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$TMPDIR" "$MPLCONFIGDIR"

check_current_role() {
  expected_label="$1"
  shift
  if ! "$PYTHON_BIN" - "$PWD" "$expected_label" "$@" <<'PY'
from pathlib import Path
import json
import sys

workspace = Path(sys.argv[1])
expected_label = sys.argv[2]
allowed_roles = sys.argv[3:]
manifest_path = workspace / ".manifests/current_role.json"
if not manifest_path.exists():
    print(
        f"Error: {expected_label} requires .manifests/current_role.json",
        file=sys.stderr,
    )
    raise SystemExit(1)
try:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_role = data["agent_name"]
except Exception as exc:
    print(
        f"Error: {expected_label} found invalid .manifests/current_role.json: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(1)
if actual_role not in allowed_roles:
    if len(allowed_roles) == 1:
        print(
            f"Error: {expected_label} requires current role {allowed_roles[0]}; found {actual_role}",
            file=sys.stderr,
        )
    else:
        allowed = ", ".join(allowed_roles)
        print(
            f"Error: {expected_label} requires one of {allowed}; found {actual_role}",
            file=sys.stderr,
        )
    raise SystemExit(1)
PY
  then
    exit 1
  fi
}

check_current_role "submit_engineering_plan.sh" engineer_planner

exec "$PYTHON_BIN" scripts/submit_plan.py "$@"
