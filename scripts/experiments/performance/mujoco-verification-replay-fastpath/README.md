# MuJoCo Verification Replay Fast Path

This note tracks the shared verifier optimization that reduced the serial replay
cost inside `worker_heavy/simulation/verification.py`.

Current state:

- MuJoCo rollout still uses batched native stepping.
- The post-rollout replay path now caches body and site ids once per scene.
- Static bodies are prechecked once, so the hot replay loop only handles moving
  bodies and derived collision checks.

Why this exists:

- the notebook workflow calls the shared verifier repeatedly during retry
  search,
- the replay pass was the dominant cost in the slow run,
- and we want a visible placeholder for future vectorization work if the next
  speed target justifies it.

Measured on the current tube-guided synthetic scene:

- before: about 3 minutes per `verify_with_jitter(...)` batch
- after: about 7 seconds for the same batch shape

Follow-up if needed:

- consider vectorizing the remaining moving-body replay checks
- keep the comments in `worker_heavy/simulation/verification.py` aligned with
  the actual hot path
