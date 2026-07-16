#!/usr/bin/env python3
"""Dry-run-first local artifact retention for one verified pipeline run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

import provenance
import redaction
import run_diagnostics
from io_utils import atomic_write_json


RETENTION_RECEIPT = "logs/retention.json"
_TRANSCRIPT_METADATA = {
    "metadata/creator_profile.json",
    "metadata/selected.compact.json",
    "metadata/selected.video_id_map.json",
    "metadata/video_id_map.json",
}


class RetentionError(ValueError):
    """A retention request is unsafe, stale, or inconsistent with the run."""


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    policy: str
    run_id: str
    delete_paths: tuple[str, ...]
    delete_bytes: int
    inventory_digest: str

    def to_dict(self, *, dry_run: bool) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "policy": self.policy,
            "dry_run": dry_run,
            "delete_count": len(self.delete_paths),
            "delete_bytes": self.delete_bytes,
            "delete_paths": list(self.delete_paths),
            "inventory_digest": self.inventory_digest,
        }


def _read_input(root: Path) -> Mapping[str, Any]:
    input_path = root / "input.json"
    provenance_path = root / "metadata" / "provenance.json"
    if not root.is_dir() or not input_path.is_file():
        raise RetentionError("retention target is not a pipeline run directory")
    if not provenance_path.is_file():
        raise RetentionError("pipeline run directory has no provenance manifest")
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RetentionError("pipeline run input.json is unreadable") from error
    if not isinstance(payload, Mapping):
        raise RetentionError("pipeline run input.json must contain an object")
    try:
        record = provenance.record_from_input(payload)
    except provenance.ProvenanceError as error:
        raise RetentionError(f"pipeline run provenance is invalid: {error}") from error
    try:
        manifest = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RetentionError("pipeline run provenance manifest is unreadable") from error
    compared_fields = (
        "schema_version",
        "source_platform",
        "source_url",
        "source_collected_at",
        "rights_basis",
        "rights_declared",
        "authorization",
        "retention_policy",
        "takedown_contact",
        "usage_boundary",
        "commercial_delivery_eligible",
    )
    if not isinstance(manifest, Mapping) or any(
        manifest.get(field) != record.get(field) for field in compared_fields
    ):
        raise RetentionError(
            "pipeline run provenance manifest is inconsistent with input.json"
        )
    return payload


def _iter_inventory(root: Path) -> Iterator[tuple[str, Path, os.stat_result]]:
    resolved_root = root.resolve(strict=True)
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for dirname in list(dirnames):
            candidate = directory_path / dirname
            if candidate.is_symlink():
                dirnames.remove(dirname)
                relative = candidate.relative_to(root).as_posix()
                yield relative, candidate, candidate.lstat()
        for filename in filenames:
            candidate = directory_path / filename
            relative = candidate.relative_to(root).as_posix()
            if not candidate.is_symlink():
                resolved = candidate.resolve(strict=True)
                try:
                    resolved.relative_to(resolved_root)
                except ValueError as error:
                    raise RetentionError(
                        f"run artifact escapes the run directory: {relative}"
                    ) from error
            yield relative, candidate, candidate.lstat()


def _keep_path(relative: str, policy: str) -> bool:
    if policy == "retain_media":
        return True
    if relative in {"input.json", "metadata/provenance.json", RETENTION_RECEIPT}:
        return True
    if relative == "skill" or relative.startswith("skill/"):
        return True
    if policy == "transcripts_only":
        if relative in _TRANSCRIPT_METADATA:
            return True
        if relative.startswith("transcripts/") and not relative.startswith(
            "transcripts/raw_json/"
        ):
            return True
    return False


def build_retention_plan(
    run_dir: Path,
    policy: str | None = None,
) -> RetentionPlan:
    """Inventory one run and return a deterministic, side-effect-free deletion plan."""
    root = Path(run_dir)
    payload = _read_input(root)
    recorded_policy = str(payload.get("retention_policy") or "")
    selected_policy = policy or recorded_policy
    if selected_policy not in provenance.RETENTION_POLICIES:
        raise RetentionError(
            "retention policy must be one of: "
            + ", ".join(provenance.RETENTION_POLICIES)
        )
    if policy is not None and policy != recorded_policy:
        raise RetentionError(
            "requested retention policy does not match the policy recorded in input.json"
        )

    delete_paths: list[str] = []
    delete_bytes = 0
    inventory = hashlib.sha256()
    for relative, _path, stat in sorted(_iter_inventory(root), key=lambda item: item[0]):
        inventory.update(
            f"{relative}\0{stat.st_mode}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode(
                "utf-8"
            )
        )
        if not _keep_path(relative, selected_policy):
            delete_paths.append(relative)
            delete_bytes += stat.st_size
    return RetentionPlan(
        policy=selected_policy,
        run_id=root.name,
        delete_paths=tuple(delete_paths),
        delete_bytes=delete_bytes,
        inventory_digest=inventory.hexdigest(),
    )


def _remove_empty_directories(root: Path) -> None:
    for directory, _dirnames, _filenames in os.walk(root, topdown=False):
        candidate = Path(directory)
        if candidate == root or candidate.is_symlink():
            continue
        try:
            candidate.rmdir()
        except OSError:
            pass


def _validated_delete_candidates(
    root: Path,
    delete_paths: tuple[str, ...],
) -> tuple[tuple[str, Path], ...]:
    """Preflight every planned path before the first destructive operation."""

    resolved_root = root.resolve(strict=True)
    candidates: list[tuple[str, Path]] = []
    for relative in delete_paths:
        portable = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or portable.is_absolute()
            or portable.as_posix() != relative
            or any(part in {"", ".", ".."} for part in portable.parts)
        ):
            raise RetentionError(
                f"unsafe deletion path must be a normalized run-relative path: {relative!r}"
            )
        candidate = root.joinpath(*portable.parts)
        try:
            resolved_parent = candidate.parent.resolve(strict=True)
            resolved_parent.relative_to(resolved_root)
            if not candidate.is_symlink():
                candidate.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as error:
            raise RetentionError(
                f"planned artifact escapes or is missing from the run: {relative!r}"
            ) from error
        candidates.append((relative, candidate))
    return tuple(candidates)


def apply_retention_plan(run_dir: Path, plan: RetentionPlan) -> dict[str, Any]:
    """Apply an unchanged plan and persist a non-secret audit receipt."""
    root = Path(run_dir)
    current = build_retention_plan(root, policy=plan.policy)
    if current != plan:
        raise RetentionError(
            "retention plan is stale because the run inventory changed; run dry-run again"
        )
    _validated_delete_candidates(root, plan.delete_paths)

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for relative in plan.delete_paths:
        try:
            # Narrow the preflight-to-unlink race for parent symlink/junction swaps.
            candidate = _validated_delete_candidates(root, (relative,))[0][1]
            if candidate.is_dir() and not candidate.is_symlink():
                raise RetentionError("planned artifact unexpectedly became a directory")
            candidate.unlink()
        except Exception as error:
            failed.append(
                {
                    "path": relative,
                    "error": redaction.scrub_text(error, limit=500),
                }
            )
            if isinstance(error, RetentionError):
                break
        else:
            deleted.append(relative)

    _remove_empty_directories(root)
    receipt = {
        "schema_version": 1,
        "run_id": root.name,
        "policy": plan.policy,
        "status": "applied" if not failed else "partial",
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "planned_delete_count": len(plan.delete_paths),
        "planned_delete_bytes": plan.delete_bytes,
        "inventory_digest": plan.inventory_digest,
        "deleted_paths": deleted,
        "failed": failed,
    }
    atomic_write_json(root / RETENTION_RECEIPT, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or apply local artifact retention for one pipeline run"
    )
    parser.add_argument("--run-dir", required=True, help="Pipeline run directory")
    parser.add_argument(
        "--policy",
        choices=provenance.RETENTION_POLICIES,
        help="Must match the retention policy recorded in input.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete listed artifacts; without this flag the command is a read-only dry-run",
    )
    args = parser.parse_args()
    try:
        run_dir = Path(args.run_dir)
        run_diagnostics.require_current_run(run_dir)
        plan = build_retention_plan(run_dir, policy=args.policy)
        output = apply_retention_plan(run_dir, plan) if args.apply else plan.to_dict(dry_run=True)
    except (RetentionError, run_diagnostics.RunFormatError) as error:
        parser.error(str(error))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if output.get("status") == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
