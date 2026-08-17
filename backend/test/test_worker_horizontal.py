"""Horizontal-scale smoke test wrapper — Week 8.4.

Skipped by default. Run with:

    TEST_POSTGRES_URL=postgresql://... \\
    FORCE_HORIZONTAL_SMOKE=1 \\
        pytest test/test_worker_horizontal.py -q

On Windows the subprocess + Postgres connection ownership is finicky, so the
test stays opt-in there even when TEST_POSTGRES_URL is set. Linux CI runs it
unconditionally when TEST_POSTGRES_URL is exported.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

REPO_BACKEND = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPO_BACKEND / "scripts" / "horizontal_smoke.py"


def _should_skip() -> str | None:
    if not os.getenv("TEST_POSTGRES_URL"):
        return "TEST_POSTGRES_URL not set"
    if platform.system() == "Windows" and not os.getenv("FORCE_HORIZONTAL_SMOKE"):
        return "Windows: set FORCE_HORIZONTAL_SMOKE=1 to opt in"
    return None


pytestmark = pytest.mark.skipif(_should_skip() is not None, reason=_should_skip() or "")


def test_horizontal_smoke_three_workers_no_double_execution(tmp_path):
    """Three workers race for 20 noop_smoke jobs; assert PASS exit code."""
    env = os.environ.copy()
    # The script reads TEST_POSTGRES_URL itself.
    proc = subprocess.run(
        [
            sys.executable,
            str(SMOKE_SCRIPT),
            "--workers", "3",
            "--jobs", "20",
            "--duration", "45",
            "--apply",
        ],
        cwd=str(REPO_BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"smoke failed (exit={proc.returncode}):\n{output}"
    assert "PASS" in proc.stdout, f"missing PASS marker:\n{output}"
