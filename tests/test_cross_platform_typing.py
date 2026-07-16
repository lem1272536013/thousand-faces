"""Keep platform-specific code type-safe on every CI operating system."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_scripts_typecheck_for_every_ci_platform(
    platform: str,
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--platform",
            platform,
            "--cache-dir",
            str(tmp_path / platform),
            "scripts",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    assert result.returncode == 0, output
