#!/usr/bin/env python3
"""Deprecated compatibility entry point for the current run quality check."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import creator_pipeline  # noqa: E402
import settings  # noqa: E402


REPLACEMENT_COMMAND = "python scripts/creator_pipeline.py quality-check --run-dir <run-dir>"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deprecated compatibility wrapper for Creator Skill quality checks",
        epilog=f"Replacement: {REPLACEMENT_COMMAND}",
    )
    parser.add_argument("run_dir", help="Current pipeline run directory")
    parser.add_argument("--env", help="Path to .env file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print a failing quality report but return exit code 0",
    )
    args = parser.parse_args()

    print(
        f"DEPRECATED: scripts/research/quality_check.py; use `{REPLACEMENT_COMMAND}`.",
        file=sys.stderr,
    )
    try:
        settings.load_settings(
            Path(args.env).expanduser() if args.env else None,
            install=True,
        )
    except settings.SettingsError as error:
        parser.error(str(error))
    return creator_pipeline.command_quality_check(args)


if __name__ == "__main__":
    raise SystemExit(main())
