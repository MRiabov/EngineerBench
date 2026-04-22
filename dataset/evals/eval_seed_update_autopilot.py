#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import runpy

if __name__ == "__main__":
    target = Path(__file__).with_name("eval_seed_update_autopilot_per_seed.py")
    runpy.run_path(str(target), run_name="__main__")
