#!/usr/bin/env python3
"""User-facing CLI for the shared offline pipeline self-test."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from offline_scenarios import OfflineScenarioError, run_and_validate_offline_happy_path


def emit(text: str, *, error: bool = False) -> None:
    if text:
        print(text, end="" if text.endswith("\n") else "\n", file=sys.stderr if error else sys.stdout)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    try:
        with tempfile.TemporaryDirectory(prefix="creator_skill_selftest_") as temp_dir:
            result = run_and_validate_offline_happy_path(project_root, Path(temp_dir))
            emit(result.baseline.stdout)
            emit(result.baseline.stderr, error=True)
            emit(result.refinement.stdout)
            emit(result.refinement.stderr, error=True)
    except OfflineScenarioError as exc:
        print(f"offline self-test failed: {exc}", file=sys.stderr)
        return 1

    print("offline self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
