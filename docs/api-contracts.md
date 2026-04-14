# Problemologist-AI - API Contracts

**Date:** 2026-03-20

## Session and Authentication Conventions

| Convention | Details |
| -- | -- |
| Session header | Most worker and controller-to-worker calls use `X-Session-ID` |
| Worker filesystem bypass | Internal/system-only escape hatch; requires both a payload flag and `X-System-FS-Bypass: 1` |
| Backup protection | `/api/ops/backup` requires `X-Backup-Secret` |
| Controller compatibility | Controller routes are available both under `/api/...` and legacy unprefixed paths for backward compatibility |

## Controller API

### Episodes

| Method | Path | Purpose | Notes |
| -- | -- | -- | -- |
| POST | `/api/episodes/{episode_id}/traces/{trace_id}/feedback` | Store feedback for a trace | Also forwards the score to Langfuse when possible |
| GET | `/api/episodes/{episode_id}/assets/{path}` | Proxy an asset from the worker | Uses the worker session ID stored in episode metadata |
| POST | `/api/episodes/{episode_id}/review` | Submit a final review decision | Validates review frontmatter and handles refusal confirmation |
| POST | `/api/episodes/{episode_id}/messages` | Send a follow-up message to an episode | Queues continuation work |
| GET | `/api/episodes/{episode_id}/electronics/schematic` | Return an electronics schematic | Builds a tscircuit-compatible schematic from `assembly_definition.yaml` |
| GET | `/api/episodes` | List episodes | Returns lightweight episode summaries |
| GET | `/api/episodes/{episode_id}` | Fetch a full episode record | Includes traces and assets |
| DELETE | `/api/episodes/{episode_id}` | Delete an episode | Removes the episode and its related data |
| WS | `/api/episodes/{episode_id}/ws` | Live episode updates | Keeps the dashboard subscribed to status changes |
| POST | `/api/episodes/{episode_id}/interrupt` | Cancel a running episode | Updates the DB state immediately |

### Benchmark

| Method | Path | Purpose | Notes |
| -- | -- | -- | -- |
| POST | `/api/benchmark/generate` | Start benchmark generation | Creates a new session and launches the benchmark graph |
| POST | `/api/benchmark/{session_id}/confirm` | Continue a benchmark after confirmation | Also stores optional user comments |
| GET | `/api/benchmark/{session_id}` | Fetch a benchmark session | Returns episode data and traces |
| POST | `/api/benchmark/{session_id}/objectives` | Update benchmark objectives | Synchronizes benchmark limits back into the session metadata |

### Script Tools

| Method | Path | Purpose | Notes |
| -- | -- | -- | -- |
| POST | `/api/script-tools/validate` | Validate a script through the worker boundary | Uses the remote filesystem middleware |
| POST | `/api/script-tools/simulate` | Simulate a script through the worker boundary | Proxies to the heavy workflow path |
| POST | `/api/script-tools/submit` | Submit a script for review | Materializes the stage-specific handoff manifest |

### Other Controller Routes

| Method | Path | Purpose |
| -- | -- | -- |
| POST | `/api/test/episodes` | Create a deterministic test episode for integration runs only |
| POST | `/api/agent/run` | Launch an agent run directly |
| GET | `/api/cots/search` | Search the COTS catalog |
| GET | `/api/cots/metadata` | Return catalog provenance metadata |
| GET | `/api/skills` | List mounted skills |
| POST | `/api/ops/backup` | Start the backup workflow |
| POST | `/api/sessions/{session_id}/steer` | Queue or start a steered prompt |
| GET | `/api/sessions/{session_id}/queue` | Inspect the queued steering prompts |

## Worker-Light API

The `/fs` namespace is a shared workspace surface with three distinct
subfamilies:

- workspace CRUD and agent tooling
- low-level probes and raw-byte inspection
- explicit snapshot transport

Use the narrowest subfamily that matches the caller's intent. Integration tests
should not use raw probe calls as generic scaffolding when a batch upload or a
direct fixture seed would be clearer.

### Service Health

| Method | Path | Purpose |
| -- | -- | -- |
| GET | `/health` | Health check |

### File Workspace Surface

| Method | Path | Purpose |
| -- | -- | -- |
| POST | `/fs/ls` | List files in the session filesystem |
| POST | `/fs/read` | Read a text file |
| POST | `/fs/write` | Write a text file |
| POST | `/fs/edit` | Apply replacements to a file |
| POST | `/fs/upload_file` | Upload a binary file |
| POST | `/fs/grep` | Search for text in files |
| POST | `/fs/delete` | Delete a file or directory |
| POST | `/fs/upload_files` | Upload multiple files in one request |
| POST | `/fs/read_files` | Read multiple files in one request |
| POST | `/fs/exists` | Check whether a path exists |
| POST | `/fs/read_blob` | Read raw bytes from a path |
| POST | `/fs/bundle` | Bundle the session workspace into a tarball |

### Git And Execution

| Method | Path | Purpose |
| -- | -- | -- |
| POST | `/git/init` | Initialize a git repository in the session workspace |
| POST | `/git/commit` | Commit workspace changes |
| GET | `/git/status` | Report git status |
| POST | `/git/resolve` | Resolve a merge conflict |
| POST | `/git/merge/abort` | Abort a merge |
| POST | `/git/merge/complete` | Complete a merge and commit it |
| POST | `/runtime/execute` | Run a shell command in the session workspace |
| GET | `/assets/{path}` | Serve a workspace asset |
| POST | `/lint` | Lint Python code with Ruff |
| POST | `/topology/inspect` | Inspect a topology target in a script |

## Worker-Heavy API

| Method | Path | Purpose | Notable Behavior |
| -- | -- | -- | -- |
| GET | `/health` | Health check | Reports the API process health |
| GET | `/ready` | Admission readiness | Returns `503` and `WORKER_BUSY` when a heavy job is active |
| POST | `/benchmark/verify` | Batched runtime-randomization verification | Produces multi-run verification results |
| POST | `/benchmark/simulate` | Physics-backed benchmark stability/evidence simulation | Returns simulation results, MJCF, renders, and failure details |
| POST | `/benchmark/validate` | Geometric validation and preview generation | Returns validation results and preview artifacts |
| POST | `/benchmark/validate_circuit` | Validate an electronics section | Builds and checks a circuit from the electronics schema |
| POST | `/benchmark/analyze` | Manufacturing analysis | Returns a workbench result with cost and manufacturability data |
| POST | `/benchmark/preview` | Render a design preview | Returns the preview image path |
| POST | `/benchmark/build` | Rebuild simulation assets | Produces the generated scene artifact |
| POST | `/benchmark/submit` | Submit handoff for review | Returns validation, simulation, renders, and review manifests when present |
| POST | `/internal/simulation/cleanup` | Internal cleanup | Resets cached simulation backend state for teardown |

## Representative Examples

### Benchmark Generation

```bash
curl -X POST http://127.0.0.1:18000/api/benchmark/generate \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "Create a funnel benchmark that teaches gravity and collision handling",
    "max_cost": 45,
    "max_weight": 1200
  }'
```

### Worker-Light File Write

```bash
curl -X POST http://127.0.0.1:18001/fs/write \
  -H 'X-Session-ID: demo-session' \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "script.py",
    "content": "print(\"hello\")",
    "overwrite": true
  }'
```

### Worker-Heavy Validation

```bash
curl -X POST http://127.0.0.1:18002/benchmark/validate \
  -H 'X-Session-ID: demo-session' \
  -H 'Content-Type: application/json' \
  -d '{
    "script_path": "script.py",
    "backend": "GENESIS"
  }'
```

## Common Error Codes

| Status | Meaning |
| -- | -- |
| 403 | Permission denied, read-only path violation, or missing backup secret |
| 404 | Missing file, asset, episode, or session |
| 422 | Invalid review frontmatter, refusal artifact, or malformed artifact payload |
| 503 | Heavy worker busy or temporary admission failure |
| 500 | Internal error, validation failure, or unsupported runtime state |

## Compatibility Notes

- The controller mounts the main route groups under both `/api/...` and the legacy unprefixed paths so older clients and integration tests keep working.
- `POST /api/test/episodes` and `/test/episodes` are only available when `IS_INTEGRATION_TEST=true`.
- `POST /api/agent/run` and `/agent/run` create a run directly, while the episode and benchmark routes are the preferred higher-level entry points for most workflows.
- `GET /ready` on worker-heavy is the admission gate for heavy compute work; a `503 WORKER_BUSY` response means the instance is already busy with another job.
