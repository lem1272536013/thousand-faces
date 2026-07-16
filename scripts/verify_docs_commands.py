#!/usr/bin/env python3
"""Verify documented commands without using provider credentials or live network calls."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import settings


DOCUMENT_PATHS = (
    Path("README.md"),
    Path("SKILL.md"),
    Path("SECURITY.md"),
    Path("CONTRIBUTING.md"),
    Path("CHANGELOG.md"),
    Path("references/pipeline.md"),
    Path("references/host_refinement.md"),
    Path("references/versioning.md"),
)
ALLOWED_MODULES = {"mypy", "pip", "pytest", "ruff", "venv"}
MODULE_SUBCOMMANDS = {
    "pip": {"check", "install"},
    "ruff": {"check"},
}
ALLOWED_SCRIPTS = {
    "build_creator_skill.py",
    "config_check.py",
    "creator_pipeline.py",
    "generate_config_docs.py",
    "prepare_host_refinement.py",
    "retention.py",
    "run_creator_skill_build.py",
    "self_test.py",
    "verify_docs_commands.py",
    "verify_release_metadata.py",
}
CREATOR_PIPELINE_SUBCOMMANDS = {
    "asr-json-to-transcript",
    "build-skill",
    "download-videos",
    "extract-audio",
    "inspect-run",
    "normalize-metadata",
    "quality-check",
    "run-summary",
    "select-samples",
    "summarize-transcripts",
}
COMMAND_FENCE = re.compile(r"```(?:powershell|bash)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
PYTHON_PREFIX = re.compile(
    r"^(?:python3?|\.\\\.venv\\Scripts\\python\.exe|\./\.venv/bin/python)\s+(?P<body>.+)$",
    re.IGNORECASE,
)
OPTION = re.compile(r"(?<!\w)--[a-zA-Z][a-zA-Z0-9-]*")
SHORT_OPTION = re.compile(r"(?<![\w-])-[a-zA-Z](?=\s|$)")
SCRIPT = re.compile(r"^scripts[\\/](?P<name>[a-zA-Z0-9_]+\.py)(?:\s+|$)")
MODULE = re.compile(r"^-m\s+(?P<name>[a-zA-Z0-9_-]+)(?:\s+|$)")


class DocumentationCommandError(RuntimeError):
    """Raised when a documented command is missing, unsafe, or no longer valid."""


@dataclass(frozen=True)
class DocumentedCommand:
    document: Path
    command: str
    script: str | None
    module: str | None
    subcommand: str | None
    options: tuple[str, ...]


def sanitized_environment() -> dict[str, str]:
    """Return a deterministic environment with every project setting removed."""

    environment = os.environ.copy()
    for key in settings.CONFIG_KEYS:
        environment.pop(key, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    return environment


def documented_python_commands(text: str) -> list[str]:
    """Return Python commands from PowerShell and Bash fences without executing them."""

    commands: list[str] = []
    for block in COMMAND_FENCE.findall(text):
        pending = ""
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            continued = line.endswith("`")
            part = line[:-1].rstrip() if continued else line
            pending = f"{pending} {part}".strip()
            if continued:
                continue
            if PYTHON_PREFIX.match(pending):
                commands.append(pending)
            pending = ""
        if pending and PYTHON_PREFIX.match(pending):
            commands.append(pending)
    return commands


def parse_documented_command(document: Path, command: str) -> DocumentedCommand:
    match = PYTHON_PREFIX.match(command)
    if match is None:
        raise DocumentationCommandError(f"unsupported command prefix in {document}: {command}")
    body = match.group("body").strip()
    script_match = SCRIPT.match(body)
    module_match = MODULE.match(body)
    script = script_match.group("name") if script_match else None
    module = module_match.group("name") if module_match else None
    if script is None and module is None:
        raise DocumentationCommandError(f"unsupported Python command in {document}: {command}")
    if script is not None and script not in ALLOWED_SCRIPTS:
        raise DocumentationCommandError(f"script is not in the documentation allowlist: {script}")
    if module is not None and module not in ALLOWED_MODULES:
        raise DocumentationCommandError(f"module is not in the documentation allowlist: {module}")

    subcommand: str | None = None
    option_body = body
    if script == "creator_pipeline.py":
        remainder = body[script_match.end() :].strip() if script_match else ""
        first = remainder.split(maxsplit=1)[0] if remainder else ""
        if first in CREATOR_PIPELINE_SUBCOMMANDS:
            subcommand = first
        elif first and not first.startswith("-"):
            raise DocumentationCommandError(f"unknown creator_pipeline subcommand: {first}")
    elif module is not None and module_match is not None:
        remainder = body[module_match.end() :].strip()
        option_body = remainder
        known_subcommands = MODULE_SUBCOMMANDS.get(module)
        if known_subcommands:
            first = remainder.split(maxsplit=1)[0] if remainder else ""
            if first in known_subcommands:
                subcommand = first
            elif first and not first.startswith("-"):
                raise DocumentationCommandError(f"unknown {module} subcommand: {first}")
    options = (*OPTION.findall(option_body), *SHORT_OPTION.findall(option_body))
    return DocumentedCommand(
        document=document,
        command=command,
        script=script,
        module=module,
        subcommand=subcommand,
        options=tuple(dict.fromkeys(options)),
    )


def run_process(
    command: list[str],
    *,
    project_root: Path,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=project_root,
        env=sanitized_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def checked_process(
    command: list[str],
    *,
    project_root: Path,
    label: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    process = run_process(command, project_root=project_root, timeout=timeout)
    if process.returncode != 0:
        detail = (process.stdout + process.stderr).strip()
        raise DocumentationCommandError(f"{label} failed ({process.returncode}): {detail[-1200:]}")
    return process


def verify_static_commands(project_root: Path) -> int:
    """Validate every documented Python command against an allowlist and CLI help."""

    parsed: list[DocumentedCommand] = []
    for relative in DOCUMENT_PATHS:
        path = project_root / relative
        if not path.is_file():
            raise DocumentationCommandError(f"missing documentation file: {relative.as_posix()}")
        text = path.read_text(encoding="utf-8")
        parsed.extend(
            parse_documented_command(relative, command)
            for command in documented_python_commands(text)
        )

    if not parsed:
        raise DocumentationCommandError("no documented Python commands were found")

    help_cache: dict[tuple[str, str | None], str] = {}
    for item in parsed:
        if item.script is not None:
            script_path = project_root / "scripts" / item.script
            if not script_path.is_file():
                raise DocumentationCommandError(f"documented script does not exist: scripts/{item.script}")
            if item.script == "self_test.py":
                continue
            cache_key = (f"script:{item.script}", item.subcommand)
            help_command = [sys.executable, str(script_path)]
            label = item.script
        elif item.module is not None:
            cache_key = (f"module:{item.module}", item.subcommand)
            help_command = [sys.executable, "-m", item.module]
            label = f"python -m {item.module}"
        else:
            raise DocumentationCommandError(f"unclassified documented command: {item.command}")
        if cache_key not in help_cache:
            if item.subcommand:
                help_command.append(item.subcommand)
            help_command.append("--help")
            process = checked_process(
                help_command,
                project_root=project_root,
                label=f"help probe for {label}",
            )
            help_cache[cache_key] = process.stdout + process.stderr
        help_text = help_cache[cache_key]
        missing = [option for option in item.options if option not in help_text]
        if missing:
            raise DocumentationCommandError(
                f"unsupported option(s) in {item.document.as_posix()}: {', '.join(missing)}"
            )
    return len(parsed)


def newest_run(run_root: Path, project_name: str) -> Path:
    project_root = run_root / project_name
    candidates = sorted(path for path in project_root.iterdir() if path.is_dir())
    if not candidates:
        raise DocumentationCommandError("offline demo did not create a run directory")
    return candidates[-1]


def verify_offline_workflow(project_root: Path) -> None:
    """Execute the documented offline workflow in a disposable directory."""

    with tempfile.TemporaryDirectory(prefix="thousand_faces_docs_") as temp_dir:
        run_root = Path(temp_dir) / "runs"
        runner = project_root / "scripts" / "run_creator_skill_build.py"
        checked_process(
            [
                sys.executable,
                str(runner),
                "--source-url",
                "https://www.douyin.com/user/offline-demo",
                "--project-name",
                "docs-offline-demo",
                "--sample-count",
                "3",
                "--raw-metadata",
                str(project_root / "tests/fixtures/corpora/tech/metadata.json"),
                "--transcripts-dir",
                str(project_root / "tests/fixtures/corpora/tech/transcripts"),
                "--skip-download",
                "--skip-audio",
                "--skip-asr",
                "--rights-basis",
                "public_research",
                "--retention-policy",
                "retain_media",
                "--takedown-contact",
                "demo@example.invalid",
                "--run-root",
                str(run_root),
            ],
            project_root=project_root,
            label="offline demo",
        )
        run_dir = newest_run(run_root, "docs-offline-demo")
        pipeline = project_root / "scripts" / "creator_pipeline.py"
        checked_process(
            [sys.executable, str(pipeline), "inspect-run", "--run-dir", str(run_dir), "--json"],
            project_root=project_root,
            label="offline run inspection",
        )
        checked_process(
            [
                sys.executable,
                str(project_root / "scripts" / "prepare_host_refinement.py"),
                "--run-dir",
                str(run_dir),
            ],
            project_root=project_root,
            label="offline host-refinement preparation",
        )
        checked_process(
            [sys.executable, str(pipeline), "quality-check", "--run-dir", str(run_dir), "--json"],
            project_root=project_root,
            label="offline quality check",
        )


def verify_executable_commands(project_root: Path) -> None:
    checked_process(
        [sys.executable, str(project_root / "scripts" / "generate_config_docs.py"), "--check"],
        project_root=project_root,
        label="generated configuration check",
    )
    verify_offline_workflow(project_root)
    checked_process(
        [sys.executable, str(project_root / "scripts" / "self_test.py")],
        project_root=project_root,
        label="offline self-test",
        timeout=180,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate documented Python commands and run credential-free examples"
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Only validate paths, allowlists, subcommands, and documented options",
    )
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    try:
        count = verify_static_commands(project_root)
        print(f"PASS static documentation commands ({count})")
        if not args.static_only:
            verify_executable_commands(project_root)
            print("PASS executable offline documentation workflow")
    except (DocumentationCommandError, OSError, subprocess.SubprocessError) as exc:
        print(f"documentation command verification failed: {exc}", file=sys.stderr)
        return 1
    print("documentation commands verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
