#!/usr/bin/env python3
"""Validate a deterministic Binder Lane synthetic transport-canary bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any


CAMPAIGN_ID = "synthetic-transport-canary"
CANDIDATE_ID = "SYN-CANARY-001"
CLAIM_CEILING = "transport-proven"
FIXTURE_KIND = "software-only-transport-canary"
COUNT_SEMANTICS = "transport-artifacts-only"

REQUIRED_PAYLOAD_PATHS = {
    "codex-binder-plan.json",
    "lineage/candidates.json",
    "locks/target-site.json",
    "media/chimerax-handoff.json",
    "media/hyperframes-handoff.json",
    "media/pymol-handoff.json",
    "media/remotion-handoff.json",
    "media/scenes.json",
    "media/storyboard.json",
    "metrics/candidates.csv",
    "metrics/metrics.json",
    "receipts/00-plan.json",
    "receipts/01-portable-artifacts.json",
    "receipts/02-handoffs.json",
    "receipts/03-report.json",
    "receipts/closeout.json",
    "report/report.md",
    "report/summary.json",
    "sequences/annotations.json",
    "sequences/synthetic-placeholder.a3m",
    "sequences/synthetic-placeholder.fasta",
    "structures/residue-map.csv",
    "structures/synthetic-placeholder.cif",
    "structures/synthetic-placeholder.pdb",
    "viewer/portable-review-checklist.md",
    "viewer/sequence-handoff.json",
    "viewer/structure-handoff.json",
}
MANIFEST_PATH = "bundle-manifest.json"
MANIFEST_HASH_PATH = "bundle-manifest.sha256"
EXPECTED_COUNTS = {
    "requested": 1,
    "produced": 1,
    "parsed": 1,
    "valid": 1,
    "passed": 1,
    "promoted": 0,
    "delivered": 1,
}
REQUIRED_RECEIPT_STAGES = {
    "plan-materialization",
    "portable-artifact-emission",
    "viewer-and-media-handoffs",
    "report-generation",
    "bundle-closeout",
}
HANDOFF_PATHS = {
    "structure_viewer": "viewer/structure-handoff.json",
    "sequence_viewer": "viewer/sequence-handoff.json",
    "pymol": "media/pymol-handoff.json",
    "chimerax": "media/chimerax-handoff.json",
    "remotion": "media/remotion-handoff.json",
    "hyperframes": "media/hyperframes-handoff.json",
}
RECEIPT_EXPECTATIONS = {
    "receipts/00-plan.json": ("SYN-RECEIPT-00", "plan-materialization", "materialized"),
    "receipts/01-portable-artifacts.json": (
        "SYN-RECEIPT-01",
        "portable-artifact-emission",
        "materialized",
    ),
    "receipts/02-handoffs.json": ("SYN-RECEIPT-02", "viewer-and-media-handoffs", "materialized"),
    "receipts/03-report.json": ("SYN-RECEIPT-03", "report-generation", "materialized"),
    "receipts/closeout.json": ("SYN-RECEIPT-04", "bundle-closeout", "assembled-pending-validation"),
}
ALLOWED_ROUTE_KINDS = {
    "local",
    "hosted-api",
    "modal",
    "runpod",
    "lambda",
    "aws",
    "aws-batch",
    "fal",
    "ssh-hpc",
    "external-adapter",
}
ALLOWED_COST_STATES = {
    "unknown",
    "estimated",
    "observed",
    "exact-fixture-zero",
    "not-applicable",
}
ALLOWED_PACKET_STATES = {"not-emitted", "emitted"}
ALLOWED_RUNTIME_STATES = {"unprobed", "available", "unavailable"}
ALLOWED_INVOCATION_STATES = {"not-run", "attempted", "completed", "failed"}
ALLOWED_OUTPUT_VALIDATION_STATES = {"not-run", "pending", "passed", "failed"}
EXPECTED_REPORT_HEADINGS = [
    "# Synthetic Binder Lane transport canary",
    "## Identity and outcome",
    "## Transport counts",
    "## Evidence boundary",
    "## Review and media handoffs",
    "## Integrity evidence",
]
FORBIDDEN_REPORT_PHRASES = (
    "proves shape",
    "status: completed",
    "robust",
    "comprehensive",
    "seamless",
    "leverages",
)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def scan_bundle_files(root: Path, errors: list[str]) -> set[str]:
    actual_files: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
        except OSError as exc:
            relative = directory.relative_to(root).as_posix() if directory != root else "."
            errors.append(f"{relative}: cannot scan bundle directory: {exc}")
            continue
        for entry in children:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                if entry.is_symlink():
                    errors.append(f"symlinks are forbidden in bundles: {relative}")
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    actual_files.add(relative)
                else:
                    errors.append(f"non-regular files are forbidden in bundles: {relative}")
            except OSError as exc:
                errors.append(f"{relative}: cannot inspect bundle entry: {exc}")
    return actual_files


def read_regular_bytes(root: Path, relative_path: str, errors: list[str]) -> bytes | None:
    current = root
    parts = PurePosixPath(relative_path).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            errors.append(f"{relative_path}: required file is missing")
            return None
        except OSError as exc:
            errors.append(f"{relative_path}: cannot inspect file: {exc}")
            return None
        if stat.S_ISLNK(mode):
            errors.append(f"{relative_path}: symlinks are forbidden")
            return None
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            errors.append(f"{relative_path}: path component is not a directory")
            return None
        if index == len(parts) - 1 and not stat.S_ISREG(mode):
            errors.append(f"{relative_path}: required file is not regular")
            return None

    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(current, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            errors.append(f"{relative_path}: required file is not regular")
            return None
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    except OSError as exc:
        errors.append(f"{relative_path}: cannot read file: {exc}")
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(root: Path, relative_path: str, errors: list[str]) -> Any:
    raw = read_regular_bytes(root, relative_path, errors)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative_path}: invalid JSON: {exc}")
        return None
    if raw != canonical_json_bytes(value):
        errors.append(f"{relative_path}: JSON is not in canonical fixture form")
    return value


def check_artifact_ref(
    ref: Any,
    manifest_entries: dict[str, dict[str, Any]],
    context: str,
    errors: list[str],
) -> None:
    if not isinstance(ref, dict):
        errors.append(f"{context}: artifact reference must be an object")
        return
    path = ref.get("path")
    if not safe_relative_path(path):
        errors.append(f"{context}: invalid relative artifact path {path!r}")
        return
    entry = manifest_entries.get(path)
    if entry is None:
        errors.append(f"{context}: artifact path is absent from manifest: {path}")
        return
    if ref.get("sha256") != entry.get("sha256"):
        errors.append(f"{context}: artifact hash does not match manifest for {path}")
    if ref.get("size_bytes") != entry.get("size_bytes"):
        errors.append(f"{context}: artifact size does not match manifest for {path}")


def is_nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def check_counts(value: Any, context: str, errors: list[str]) -> bool:
    if not isinstance(value, dict) or set(value) != set(EXPECTED_COUNTS):
        errors.append(f"{context}: counts must contain the required count keys")
        return False
    if any(not is_nonnegative_integer(item) for item in value.values()):
        errors.append(f"{context}: counts must be non-negative whole numbers")
        return False
    return True


def check_cost(value: Any, context: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{context}: cost must be an object")
        return
    status = value.get("status")
    estimate = value.get("estimate_usd")
    observed = value.get("observed_usd")
    if status not in ALLOWED_COST_STATES:
        errors.append(f"{context}: unsupported cost status")
        return
    for field, amount in (("estimate_usd", estimate), ("observed_usd", observed)):
        if amount is not None and (
            isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0
        ):
            errors.append(f"{context}: {field} must be null or a non-negative number")
    if status in {"unknown", "not-applicable"} and (estimate is not None or observed is not None):
        errors.append(f"{context}: unknown or not-applicable costs must be null")
    if status == "estimated" and estimate is None:
        errors.append(f"{context}: estimated cost requires estimate_usd")
    if status == "observed" and observed is None:
        errors.append(f"{context}: observed cost requires observed_usd")
    if status == "exact-fixture-zero" and (estimate != 0 or observed != 0):
        errors.append(f"{context}: exact-fixture-zero costs must both equal zero")


def check_execution_state(
    value: Any,
    output_artifacts: Any,
    context: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{context}: execution_state must be an object")
        return
    packet = value.get("packet")
    runtime = value.get("runtime")
    invocation = value.get("invocation")
    output_validation = value.get("output_validation")
    if packet not in ALLOWED_PACKET_STATES:
        errors.append(f"{context}: unsupported packet state")
    if runtime not in ALLOWED_RUNTIME_STATES:
        errors.append(f"{context}: unsupported runtime state")
    if invocation not in ALLOWED_INVOCATION_STATES:
        errors.append(f"{context}: unsupported invocation state")
    if output_validation not in ALLOWED_OUTPUT_VALIDATION_STATES:
        errors.append(f"{context}: unsupported output validation state")
    if packet == "not-emitted" and (
        runtime != "unprobed" or invocation != "not-run" or output_validation != "not-run"
    ):
        errors.append(f"{context}: an un-emitted packet cannot have runtime or invocation state")
    if runtime in {"unprobed", "unavailable"} and (
        invocation != "not-run" or output_validation != "not-run"
    ):
        errors.append(f"{context}: an unprobed or unavailable runtime cannot be invoked")
    if invocation in {"not-run", "attempted", "failed"} and output_validation != "not-run":
        errors.append(f"{context}: output validation requires a completed invocation")
    if invocation == "completed" and output_validation == "not-run":
        errors.append(f"{context}: completed invocation requires pending or final output validation")
    outputs = output_artifacts if isinstance(output_artifacts, list) else None
    if outputs is None:
        errors.append(f"{context}: output_artifacts must be an array")
    elif invocation != "completed" and outputs:
        errors.append(f"{context}: output artifacts require a completed invocation")
    if output_validation in {"pending", "passed"} and not outputs:
        errors.append(f"{context}: pending or passed output validation requires output artifacts")


def referenced_artifact_paths(refs: Any) -> set[str]:
    if not isinstance(refs, list):
        return set()
    return {ref.get("path") for ref in refs if isinstance(ref, dict) and isinstance(ref.get("path"), str)}


def check_report_markdown(report: bytes | None, summary: Any, errors: list[str]) -> None:
    if report is None:
        return
    try:
        text = report.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("report: report.md must be UTF-8")
        return
    headings = [heading for heading in EXPECTED_REPORT_HEADINGS if heading in text]
    if headings != EXPECTED_REPORT_HEADINGS:
        errors.append("report: required headings are missing or out of order")
    positions = [text.find(heading) for heading in EXPECTED_REPORT_HEADINGS]
    if positions != sorted(positions) or any(position < 0 for position in positions):
        errors.append("report: required headings must appear once in order")
    for phrase in FORBIDDEN_REPORT_PHRASES:
        if phrase in text.lower():
            errors.append(f"report: forbidden phrase {phrase!r}")
    if text.count("Claim ceiling: `transport-proven`") != 1:
        errors.append("report: claim ceiling statement must appear exactly once")
    if not isinstance(summary, dict):
        return
    required_text = {
        f"`{summary.get('campaign_id')}`",
        f"`{summary.get('candidate_id')}`",
        f"`{summary.get('fixture_kind')}`",
        f"Claim ceiling: `{summary.get('claim_ceiling')}`",
        "`locks/target-site.json`",
        "`bundle-manifest.json`",
        "`bundle-manifest.sha256`",
    }
    for item in required_text:
        if item not in text:
            errors.append(f"report: summary fact missing from Markdown: {item}")
    counts = summary.get("counts")
    if isinstance(counts, dict):
        for label, key in (
            ("Requested", "requested"),
            ("Produced", "produced"),
            ("Parsed", "parsed"),
            ("Valid", "valid"),
            ("Passed", "passed"),
            ("Promoted", "promoted"),
            ("Delivered", "delivered"),
        ):
            if f"| {label} | {counts.get(key)} |" not in text:
                errors.append(f"report: {key} count does not match summary")
    if summary.get("ranking_status") == "unranked" and "| Ranking | Unranked |" not in text:
        errors.append("report: unranked status is missing or mismatched")
    if summary.get("scientific_score") is None and "| Scientific score | Not measured |" not in text:
        errors.append("report: null scientific score must render as Not measured")
    if summary.get("scientific_confidence") is None and "| Scientific confidence | Not measured |" not in text:
        errors.append("report: null scientific confidence must render as Not measured")
    cost = summary.get("cost")
    if isinstance(cost, dict) and cost.get("observed_usd") == 0 and "| Observed cost | $0.00 |" not in text:
        errors.append("report: observed cost does not match summary")
    handoffs = summary.get("handoffs")
    if isinstance(handoffs, dict):
        for name, path in HANDOFF_PATHS.items():
            row = handoffs.get(name)
            if not isinstance(row, dict) or row.get("path") != path or f"`{path}`" not in text:
                errors.append(f"report: {name} handoff is missing or mismatched")
                continue
            states = row.get("execution_state")
            if not isinstance(states, dict):
                errors.append(f"report: {name} execution state is missing")
                continue
            label = {
                "structure_viewer": "Structure Viewer",
                "sequence_viewer": "Sequence Viewer",
                "pymol": "PyMOL",
                "chimerax": "ChimeraX",
                "remotion": "Remotion",
                "hyperframes": "HyperFrames",
            }[name]
            display_state = {
                "emitted": "Emitted",
                "unprobed": "Unprobed",
                "not-run": "Not run",
            }
            expected_row = (
                f"| {label} — `{path}` | {display_state.get(states.get('packet'), states.get('packet'))} | "
                f"{display_state.get(states.get('runtime'), states.get('runtime'))} | "
                f"{display_state.get(states.get('invocation'), states.get('invocation'))} | "
                f"{display_state.get(states.get('output_validation'), states.get('output_validation'))} | "
                f"{row.get('output_count')} |"
            )
            if expected_row not in text:
                errors.append(f"report: {name} state or output count does not match summary")


def validate_bundle(root: Path) -> list[str]:
    root = root.expanduser().absolute()
    errors: list[str] = []
    if root.is_symlink():
        return [f"bundle root must not be a symlink: {root}"]
    if not root.is_dir():
        return [f"bundle root is not a directory: {root}"]

    actual_files = scan_bundle_files(root, errors)
    expected_files = REQUIRED_PAYLOAD_PATHS | {MANIFEST_PATH, MANIFEST_HASH_PATH}
    for missing in sorted(expected_files - actual_files):
        errors.append(f"required file is missing: {missing}")
    for unexpected in sorted(actual_files - expected_files):
        errors.append(f"unmanifested or unexpected file: {unexpected}")
    if MANIFEST_PATH not in actual_files:
        return errors

    manifest = load_json(root, MANIFEST_PATH, errors)
    if not isinstance(manifest, dict):
        errors.append("bundle-manifest.json: root must be an object")
        return errors
    if manifest.get("schema_version") != "codex-binder-bundle-manifest/v1":
        errors.append("bundle-manifest.json: unsupported schema_version")
    if manifest.get("campaign_id") != CAMPAIGN_ID:
        errors.append("bundle-manifest.json: campaign_id mismatch")
    if manifest.get("fixture_kind") != "software-only-transport-canary":
        errors.append("bundle-manifest.json: fixture_kind mismatch")
    if manifest.get("claim_ceiling") != CLAIM_CEILING:
        errors.append("bundle-manifest.json: claim ceiling must be transport-proven")
    if manifest.get("counts") != EXPECTED_COUNTS:
        errors.append("bundle-manifest.json: deterministic canary counts mismatch")

    files = manifest.get("files")
    if not isinstance(files, list):
        errors.append("bundle-manifest.json: files must be an array")
        files = []
    paths: list[str] = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            errors.append(f"bundle-manifest.json: files[{index}] must be an object")
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            errors.append(f"bundle-manifest.json: files[{index}].path must be a string")
            continue
        paths.append(path)
    if paths != sorted(paths):
        errors.append("bundle-manifest.json: file entries must be sorted by path")
    if len(paths) != len(set(paths)):
        errors.append("bundle-manifest.json: duplicate file paths")
    if set(paths) != REQUIRED_PAYLOAD_PATHS:
        errors.append("bundle-manifest.json: payload file set mismatch")

    manifest_entries: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            continue
        relative_path = entry.get("path")
        if not safe_relative_path(relative_path):
            errors.append(f"bundle-manifest.json: files[{index}].path is not a safe relative path")
            continue
        if relative_path in {MANIFEST_PATH, MANIFEST_HASH_PATH}:
            errors.append(f"bundle-manifest.json: manifest cannot list itself: {relative_path}")
            continue
        manifest_entries[relative_path] = entry
        data = read_regular_bytes(root, relative_path, errors)
        if data is None:
            continue
        if entry.get("size_bytes") != len(data):
            errors.append(f"size mismatch: {relative_path}")
        if entry.get("sha256") != sha256_bytes(data):
            errors.append(f"hash mismatch: {relative_path}")

    if MANIFEST_HASH_PATH in actual_files:
        hash_bytes = read_regular_bytes(root, MANIFEST_HASH_PATH, errors)
        manifest_bytes = read_regular_bytes(root, MANIFEST_PATH, errors)
        if hash_bytes is not None and manifest_bytes is not None:
            hash_line = hash_bytes.decode("ascii", errors="replace")
            match = re.fullmatch(r"([0-9a-f]{64})  bundle-manifest\.json\n", hash_line)
            expected_hash = sha256_bytes(manifest_bytes)
            if not match or match.group(1) != expected_hash:
                errors.append("bundle-manifest.sha256: manifest hash mismatch")

    plan = load_json(root, "codex-binder-plan.json", errors)
    target_lock = load_json(root, "locks/target-site.json", errors)
    metrics = load_json(root, "metrics/metrics.json", errors)
    lineage = load_json(root, "lineage/candidates.json", errors)
    summary = load_json(root, "report/summary.json", errors)
    structure_handoff = load_json(root, "viewer/structure-handoff.json", errors)
    sequence_handoff = load_json(root, "viewer/sequence-handoff.json", errors)
    scenes = load_json(root, "media/scenes.json", errors)
    storyboard = load_json(root, "media/storyboard.json", errors)
    report_bytes = read_regular_bytes(root, "report/report.md", errors)

    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("evidence"), dict)
        or plan["evidence"].get("claim_ceiling") != CLAIM_CEILING
    ):
        errors.append("plan: claim ceiling must be transport-proven")
    if not isinstance(summary, dict) or summary.get("claim_ceiling") != CLAIM_CEILING:
        errors.append("summary: claim ceiling must be transport-proven")
    if isinstance(plan, dict):
        fixture = plan.get("fixture")
        if not isinstance(fixture, dict) or fixture.get("non_biological") is not True:
            errors.append("plan: fixture must be explicitly non-biological")
        if plan.get("campaign_id") != CAMPAIGN_ID:
            errors.append("plan: campaign_id mismatch")
        target = plan.get("target")
        if not isinstance(target, dict):
            errors.append("plan: target must be an object")
        else:
            check_artifact_ref(target.get("target_lock"), manifest_entries, "plan.target_lock", errors)
    if not isinstance(target_lock, dict):
        errors.append("target lock: root must be an object")
    else:
        if target_lock.get("schema_version") != "codex-binder-target-site-lock/v1":
            errors.append("target lock: unsupported schema_version")
        for field, expected in (
            ("campaign_id", CAMPAIGN_ID),
            ("target_id", "SYNTHETIC-PLACEHOLDER"),
            ("fixture_kind", FIXTURE_KIND),
            ("claim_ceiling", CLAIM_CEILING),
        ):
            if target_lock.get(field) != expected:
                errors.append(f"target lock: {field} mismatch")
        if target_lock.get("non_biological") is not True or target_lock.get("confidentiality") != "public":
            errors.append("target lock: canary classification mismatch")
        source_lock = target_lock.get("source_lock")
        if not isinstance(source_lock, dict) or any(
            not is_sha256(source_lock.get(field)) for field in ("source_sha256", "input_sha256")
        ):
            errors.append("target lock: source lock hashes are required")
        check_artifact_ref(target_lock.get("primary_input"), manifest_entries, "target lock.primary_input", errors)
        check_artifact_ref(target_lock.get("residue_map"), manifest_entries, "target lock.residue_map", errors)
        chains = target_lock.get("chains")
        if chains != [{"source_chain_id": "A", "campaign_chain_id": "A", "role": "target"}]:
            errors.append("target lock: chain mapping mismatch")
        site = target_lock.get("site")
        expected_site = {
            "site_id": "SYN-SITE-001",
            "mode": "explicit-residues",
            "numbering_scheme": "synthetic fixture numbering",
            "residues": [
                {
                    "campaign_chain_id": "A",
                    "campaign_residue_number": 1,
                    "author_residue_number": "1",
                    "insertion_code": None,
                }
            ],
            "evidence": "Software sentinel; no scientific interpretation.",
        }
        if site != expected_site:
            errors.append("target lock: site or residue numbering mismatch")
    if not isinstance(metrics, dict) or metrics.get("counts") != EXPECTED_COUNTS:
        errors.append("metrics: deterministic counts mismatch")
    else:
        if metrics.get("schema_version") != "codex-binder-metrics/v1" or metrics.get("campaign_id") != CAMPAIGN_ID:
            errors.append("metrics: schema or campaign mismatch")
        if metrics.get("count_semantics") != COUNT_SEMANTICS:
            errors.append("metrics: count semantics mismatch")
        if metrics.get("ranking_status") != "unranked":
            errors.append("metrics: root ranking status must remain unranked")
        definitions = metrics.get("definitions")
        expected_metric_ids = {
            "fixture_transport_valid",
            "scientific_confidence",
            "scientific_score",
        }
        definition_ids = (
            [item.get("metric_id") for item in definitions if isinstance(item, dict)]
            if isinstance(definitions, list)
            else []
        )
        if (
            not isinstance(definitions, list)
            or any(not isinstance(metric_id, str) for metric_id in definition_ids)
            or len(definition_ids) != len(definitions)
            or len(definition_ids) != len(set(definition_ids))
            or set(definition_ids) != expected_metric_ids
        ):
            errors.append("metrics: definitions must name each fixture metric exactly once")
        elif any(
            not isinstance(item, dict)
            or item.get("evidence_class") not in {"transport", "scientific"}
            or item.get("direction") not in {"maximize", "minimize"}
            for item in definitions
        ):
            errors.append("metrics: invalid metric definition")
        records = metrics.get("records")
        if not isinstance(records, list) or len(records) != 1:
            errors.append("metrics: exactly one sentinel record is required")
        else:
            record = records[0]
            if not isinstance(record, dict) or record.get("candidate_id") != CANDIDATE_ID:
                errors.append("metrics: sentinel candidate_id mismatch")
            elif record.get("scientific_score") is not None or record.get("scientific_confidence") is not None:
                errors.append("metrics: scientific values must remain null in the transport canary")
            elif record.get("ranking_status") != "unranked":
                errors.append("metrics: transport canary must remain unranked")
            else:
                values = record.get("values")
                states = record.get("states")
                if not isinstance(values, dict) or set(values) != expected_metric_ids:
                    errors.append("metrics: record values must match definitions")
                if not isinstance(states, dict) or set(states) != expected_metric_ids:
                    errors.append("metrics: record states must match definitions")
                elif (
                    states.get("fixture_transport_valid") != "measured"
                    or states.get("scientific_score") != "not-measured"
                    or states.get("scientific_confidence") != "not-measured"
                ):
                    errors.append("metrics: fixture metric states mismatch")
                if (
                    not isinstance(values, dict)
                    or values.get("fixture_transport_valid") != record.get("fixture_transport_valid")
                    or values.get("scientific_score") is not None
                    or values.get("scientific_confidence") is not None
                ):
                    errors.append("metrics: value null semantics or legacy parity mismatch")
    if not isinstance(summary, dict) or summary.get("counts") != EXPECTED_COUNTS:
        errors.append("summary: deterministic counts mismatch")
    elif summary.get("scientific_score") is not None or summary.get("scientific_confidence") is not None:
        errors.append("summary: scientific values must remain null")
    if isinstance(summary, dict):
        if summary.get("schema_version") != "codex-binder-closeout/v1" or summary.get("campaign_id") != CAMPAIGN_ID:
            errors.append("summary: schema or campaign mismatch")
        if summary.get("count_semantics") != COUNT_SEMANTICS or summary.get("ranking_status") != "unranked":
            errors.append("summary: count semantics or ranking mismatch")
        check_artifact_ref(summary.get("target_lock"), manifest_entries, "summary.target_lock", errors)
        check_cost(summary.get("cost"), "summary", errors)
        if summary.get("observed_cost_usd") != 0:
            errors.append("summary: observed cost mismatch")
        if summary.get("receipt_ids") != [
            "SYN-RECEIPT-00",
            "SYN-RECEIPT-01",
            "SYN-RECEIPT-02",
            "SYN-RECEIPT-03",
            "SYN-RECEIPT-04",
        ]:
            errors.append("summary: receipt IDs mismatch")

    if not isinstance(lineage, dict):
        errors.append("lineage: root must be an object")
    else:
        candidates = lineage.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            errors.append("lineage: exactly one sentinel candidate is required")
        else:
            candidate = candidates[0]
            if not isinstance(candidate, dict) or candidate.get("candidate_id") != CANDIDATE_ID:
                errors.append("lineage: candidate_id mismatch")
            elif candidate.get("parent_ids") != [] or candidate.get("round") != 0:
                errors.append("lineage: canary must have no parents and remain in round zero")
            else:
                artifact_paths = candidate.get("artifact_paths")
                if not isinstance(artifact_paths, list):
                    errors.append("lineage: artifact_paths must be an array")
                else:
                    for artifact_path in artifact_paths:
                        if not safe_relative_path(artifact_path) or artifact_path not in manifest_entries:
                            errors.append(f"lineage: unknown artifact path {artifact_path!r}")

    candidate_artifact_paths = {
        "sequences/synthetic-placeholder.fasta",
        "sequences/synthetic-placeholder.a3m",
        "structures/synthetic-placeholder.pdb",
        "structures/synthetic-placeholder.cif",
    }
    for name, handoff, expected_schema in (
        ("structure handoff", structure_handoff, "codex-binder-structure-handoff/v1"),
        ("sequence handoff", sequence_handoff, "codex-binder-sequence-handoff/v1"),
    ):
        if not isinstance(handoff, dict) or handoff.get("candidate_id") != CANDIDATE_ID:
            errors.append(f"{name}: candidate_id mismatch")
            continue
        if handoff.get("schema_version") != expected_schema or handoff.get("campaign_id") != CAMPAIGN_ID:
            errors.append(f"{name}: schema or campaign mismatch")
        if handoff.get("fixture_kind") != FIXTURE_KIND or handoff.get("non_biological") is not True:
            errors.append(f"{name}: fixture classification mismatch")
        if handoff.get("claim_ceiling") != CLAIM_CEILING:
            errors.append(f"{name}: claim ceiling mismatch")
        check_artifact_ref(handoff.get("target_lock"), manifest_entries, f"{name}.target_lock", errors)
        check_execution_state(
            handoff.get("execution_state"), handoff.get("output_artifacts"), name, errors
        )
        ref_fields = (
            ["residue_map"] if name == "structure handoff" else ["annotations"]
        )
        list_field = "coordinate_artifacts" if name == "structure handoff" else "sequence_artifacts"
        refs = handoff.get(list_field)
        if not isinstance(refs, list) or len(refs) != 2:
            errors.append(f"{name}: expected two portable artifact references")
        else:
            for index, ref in enumerate(refs):
                check_artifact_ref(ref, manifest_entries, f"{name}.{list_field}[{index}]", errors)
                if isinstance(ref, dict) and ref.get("path") not in candidate_artifact_paths:
                    errors.append(f"{name}: artifact is not owned by the sentinel candidate")
        for field in ref_fields:
            check_artifact_ref(handoff.get(field), manifest_entries, f"{name}.{field}", errors)
        if not isinstance(handoff.get("output_artifacts"), list):
            errors.append(f"{name}: output_artifacts must be an array")
        else:
            for index, ref in enumerate(handoff["output_artifacts"]):
                check_artifact_ref(ref, manifest_entries, f"{name}.output_artifacts[{index}]", errors)
        if name == "structure handoff" and handoff.get("chain_roles") != {"A": "synthetic-sentinel"}:
            errors.append("structure handoff: chain roles mismatch")

    if not isinstance(scenes, dict) or scenes.get("arbitrary_commands_allowed") is not False:
        errors.append("media scenes: arbitrary commands must be forbidden")
    else:
        if scenes.get("schema_version") != "codex-binder-media-scenes/v1" or scenes.get("campaign_id") != CAMPAIGN_ID:
            errors.append("media scenes: schema or campaign mismatch")
        if scenes.get("claim_ceiling") != CLAIM_CEILING:
            errors.append("media scenes: claim ceiling mismatch")
        check_artifact_ref(scenes.get("target_lock"), manifest_entries, "media scenes.target_lock", errors)
        scene_rows = scenes.get("scenes")
        if not isinstance(scene_rows, list) or len(scene_rows) != 1:
            errors.append("media scenes: exactly one scene is required")
        else:
            scene = scene_rows[0] if isinstance(scene_rows[0], dict) else None
            if not isinstance(scene, dict) or scene.get("scene_id") != "SYN-SCENE-001" or scene.get("candidate_id") != CANDIDATE_ID:
                errors.append("media scenes: scene ID or candidate mismatch")
            check_artifact_ref(
                scene.get("coordinate_artifact") if isinstance(scene, dict) else None,
                manifest_entries,
                "media scenes.coordinate_artifact",
                errors,
            )
            if isinstance(scene, dict) and scene.get("scientific_interpretation") is not None:
                errors.append("media scenes: scientific interpretation must remain null")
    if not isinstance(storyboard, dict) or storyboard.get("total_frames") != 90:
        errors.append("media storyboard: deterministic duration mismatch")
    else:
        shots = storyboard.get("shots")
        if (
            not isinstance(shots, list)
            or len(shots) != 1
            or not isinstance(shots[0], dict)
            or shots[0].get("scene_id") != "SYN-SCENE-001"
        ):
            errors.append("media storyboard: scene reference mismatch")

    for renderer in ("pymol", "chimerax"):
        handoff = load_json(root, f"media/{renderer}-handoff.json", errors)
        if not isinstance(handoff, dict) or handoff.get("renderer") != renderer:
            errors.append(f"{renderer} handoff: renderer mismatch")
            continue
        if handoff.get("schema_version") != "codex-binder-renderer-handoff/v1" or handoff.get("campaign_id") != CAMPAIGN_ID:
            errors.append(f"{renderer} handoff: schema or campaign mismatch")
        if (
            handoff.get("fixture_kind") != FIXTURE_KIND
            or handoff.get("non_biological") is not True
            or handoff.get("claim_ceiling") != CLAIM_CEILING
        ):
            errors.append(f"{renderer} handoff: fixture classification or claim ceiling mismatch")
        check_execution_state(
            handoff.get("execution_state"), handoff.get("output_artifacts"), f"{renderer} handoff", errors
        )
        outputs = handoff.get("output_artifacts")
        if isinstance(outputs, list):
            for index, ref in enumerate(outputs):
                check_artifact_ref(ref, manifest_entries, f"{renderer} handoff.output_artifacts[{index}]", errors)
        if handoff.get("arbitrary_commands_allowed") is not False:
            errors.append(f"{renderer} handoff: arbitrary commands must be forbidden")
        if handoff.get("required_executable") != renderer:
            errors.append(f"{renderer} handoff: executable identity mismatch")
        expected_renderer_pattern = (PurePosixPath("renders") / renderer / "{scene_id}.png").as_posix()
        if handoff.get("output_pattern") != expected_renderer_pattern:
            errors.append(f"{renderer} handoff: output pattern mismatch")
        check_artifact_ref(handoff.get("scene_manifest"), manifest_entries, f"{renderer} handoff", errors)
    for framework in ("remotion", "hyperframes"):
        handoff = load_json(root, f"media/{framework}-handoff.json", errors)
        if not isinstance(handoff, dict) or handoff.get("framework") != framework:
            errors.append(f"{framework} handoff: framework mismatch")
            continue
        if handoff.get("schema_version") != "codex-binder-video-handoff/v1" or handoff.get("campaign_id") != CAMPAIGN_ID:
            errors.append(f"{framework} handoff: schema or campaign mismatch")
        if (
            handoff.get("fixture_kind") != FIXTURE_KIND
            or handoff.get("non_biological") is not True
            or handoff.get("claim_ceiling") != CLAIM_CEILING
        ):
            errors.append(f"{framework} handoff: fixture classification or claim ceiling mismatch")
        check_execution_state(
            handoff.get("execution_state"), handoff.get("output_artifacts"), f"{framework} handoff", errors
        )
        outputs = handoff.get("output_artifacts")
        if isinstance(outputs, list):
            for index, ref in enumerate(outputs):
                check_artifact_ref(ref, manifest_entries, f"{framework} handoff.output_artifacts[{index}]", errors)
        if handoff.get("network_assets_allowed") is not False:
            errors.append(f"{framework} handoff: network assets must be forbidden")
        if "validation_gates" in handoff or not isinstance(handoff.get("planned_checks"), list):
            errors.append(f"{framework} handoff: use planned_checks rather than validation_gates")
        expected_checks = {
            "remotion": ["props-validated", "midpoint-still", "render-not-run"],
            "hyperframes": ["check-strict", "midpoint-snapshot", "preview-approval"],
        }[framework]
        if handoff.get("planned_checks") != expected_checks:
            errors.append(f"{framework} handoff: planned checks mismatch")
        expected_pattern = (
            PurePosixPath("renders") / framework / "synthetic-transport-canary.mp4"
        ).as_posix()
        if handoff.get("output_pattern") != expected_pattern:
            errors.append(f"{framework} handoff: output pattern mismatch")
        check_artifact_ref(handoff.get("storyboard"), manifest_entries, f"{framework} handoff", errors)

    receipt_stages: set[str] = set()
    receipts: dict[str, dict[str, Any]] = {}
    for receipt_path in sorted(RECEIPT_EXPECTATIONS):
        receipt = load_json(root, receipt_path, errors)
        if not isinstance(receipt, dict):
            errors.append(f"{receipt_path}: receipt root must be an object")
            continue
        receipts[receipt_path] = receipt
        expected_id, expected_stage, expected_status = RECEIPT_EXPECTATIONS[receipt_path]
        if receipt.get("schema_version") != "codex-binder-stage-receipt/v1":
            errors.append(f"{receipt_path}: unsupported schema_version")
        if receipt.get("receipt_id") != expected_id or receipt.get("stage_id") != expected_stage:
            errors.append(f"{receipt_path}: receipt ID or stage mismatch")
        stage_id = receipt.get("stage_id")
        if not isinstance(stage_id, str):
            errors.append(f"{receipt_path}: stage_id must be a string")
        else:
            receipt_stages.add(stage_id)
        if receipt.get("campaign_id") != CAMPAIGN_ID or receipt.get("status") != expected_status:
            errors.append(f"{receipt_path}: campaign or scoped status mismatch")
        if receipt.get("route_kind") not in ALLOWED_ROUTE_KINDS or not isinstance(receipt.get("provider"), str):
            errors.append(f"{receipt_path}: route kind and provider are required")
        if "route" in receipt:
            errors.append(f"{receipt_path}: legacy route field is forbidden")
        if receipt.get("route_kind") != "local" or receipt.get("provider") != "synthetic-fixture-emitter":
            errors.append(f"{receipt_path}: fixture route or provider mismatch")
        if receipt.get("candidate_ids") != [CANDIDATE_ID] or receipt.get("parent_ids") != [] or receipt.get("child_ids") != []:
            errors.append(f"{receipt_path}: candidate lineage mismatch")
        if receipt.get("count_semantics") != "transport-artifacts-only":
            errors.append(f"{receipt_path}: count semantics mismatch")
        if receipt.get("claim_ceiling") != CLAIM_CEILING:
            errors.append(f"{receipt_path}: claim ceiling mismatch")
        if receipt.get("counts") != EXPECTED_COUNTS:
            errors.append(f"{receipt_path}: counts mismatch")
        check_cost(receipt.get("cost"), f"{receipt_path}", errors)
        for field in ("inputs", "outputs"):
            refs = receipt.get(field)
            if not isinstance(refs, list):
                errors.append(f"{receipt_path}: {field} must be an array")
                continue
            for index, ref in enumerate(refs):
                check_artifact_ref(ref, manifest_entries, f"{receipt_path}.{field}[{index}]", errors)
    if receipt_stages != REQUIRED_RECEIPT_STAGES:
        errors.append("receipts: required stage set mismatch")
    closeout = receipts.get("receipts/closeout.json")
    required_receipt_dependencies = {
        "receipts/00-plan.json": {
            "outputs": {"locks/target-site.json", "codex-binder-plan.json"},
        },
        "receipts/01-portable-artifacts.json": {
            "inputs": {"locks/target-site.json", "codex-binder-plan.json"},
            "outputs": {
                "lineage/candidates.json",
                "metrics/candidates.csv",
                "metrics/metrics.json",
                "sequences/annotations.json",
                "sequences/synthetic-placeholder.a3m",
                "sequences/synthetic-placeholder.fasta",
                "structures/residue-map.csv",
                "structures/synthetic-placeholder.cif",
                "structures/synthetic-placeholder.pdb",
            },
        },
        "receipts/02-handoffs.json": {
            "inputs": {"locks/target-site.json", "codex-binder-plan.json"},
            "outputs": set(HANDOFF_PATHS.values()) | {
                "media/scenes.json",
                "media/storyboard.json",
                "viewer/portable-review-checklist.md",
            },
        },
        "receipts/03-report.json": {
            "inputs": {"locks/target-site.json", "codex-binder-plan.json", *HANDOFF_PATHS.values()},
            "outputs": {"report/report.md", "report/summary.json"},
        },
    }
    for receipt_path, field_requirements in required_receipt_dependencies.items():
        receipt = receipts.get(receipt_path)
        if not isinstance(receipt, dict):
            continue
        for field, required_paths in field_requirements.items():
            present_paths = referenced_artifact_paths(receipt.get(field))
            if not required_paths.issubset(present_paths):
                errors.append(f"{receipt_path}: required {field} dependencies are missing")
    if isinstance(closeout, dict):
        closeout_paths = referenced_artifact_paths(closeout.get("inputs"))
        required_closeout_paths = {
            "locks/target-site.json",
            "codex-binder-plan.json",
            "report/report.md",
            "report/summary.json",
            *set(RECEIPT_EXPECTATIONS) - {"receipts/closeout.json"},
        }
        if not required_closeout_paths.issubset(closeout_paths):
            errors.append("closeout receipt: required artifacts or earlier receipts are missing")

    if isinstance(summary, dict):
        handoffs = summary.get("handoffs")
        handoff_payloads = {
            "structure_viewer": structure_handoff,
            "sequence_viewer": sequence_handoff,
            "pymol": load_json(root, "media/pymol-handoff.json", errors),
            "chimerax": load_json(root, "media/chimerax-handoff.json", errors),
            "remotion": load_json(root, "media/remotion-handoff.json", errors),
            "hyperframes": load_json(root, "media/hyperframes-handoff.json", errors),
        }
        if not isinstance(handoffs, dict) or set(handoffs) != set(HANDOFF_PATHS):
            errors.append("summary: handoff set mismatch")
        else:
            for name, path in HANDOFF_PATHS.items():
                row = handoffs.get(name)
                payload = handoff_payloads[name]
                if not isinstance(row, dict) or not isinstance(payload, dict):
                    errors.append(f"summary: {name} handoff must be an object")
                    continue
                if row.get("path") != path or row.get("execution_state") != payload.get("execution_state"):
                    errors.append(f"summary: {name} handoff state mismatch")
                payload_outputs = payload.get("output_artifacts")
                if not isinstance(payload_outputs, list):
                    errors.append(f"summary: {name} output_artifacts must be an array")
                elif row.get("output_count") != len(payload_outputs):
                    errors.append(f"summary: {name} output count mismatch")
        check_report_markdown(report_bytes, summary, errors)

    fasta_bytes = read_regular_bytes(root, "sequences/synthetic-placeholder.fasta", errors)
    a3m_bytes = read_regular_bytes(root, "sequences/synthetic-placeholder.a3m", errors)
    for name, data in (("FASTA", fasta_bytes), ("A3M", a3m_bytes)):
        if data is None:
            continue
        text = data.decode("ascii", errors="replace")
        lines = text.splitlines()
        if len(lines) != 2 or not lines[0].startswith(">SYN-CANARY-001 ") or lines[1] != "XXXX":
            errors.append(f"{name}: only the fixed X-only software sentinel is allowed")
    pdb_bytes = read_regular_bytes(root, "structures/synthetic-placeholder.pdb", errors)
    cif_bytes = read_regular_bytes(root, "structures/synthetic-placeholder.cif", errors)
    if pdb_bytes is not None:
        pdb = pdb_bytes.decode("ascii", errors="replace")
        if "SOFTWARE FIXTURE ONLY" not in pdb or "ATOM      1" not in pdb or not pdb.endswith("END\n"):
            errors.append("PDB: synthetic placeholder shape mismatch")
    if cif_bytes is not None:
        cif = cif_bytes.decode("ascii", errors="replace")
        if not cif.startswith("data_SYNTHETIC_PLACEHOLDER\n") or "_atom_site.Cartn_z" not in cif:
            errors.append("mmCIF: synthetic placeholder shape mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        errors = validate_bundle(args.bundle)
    except Exception as exc:  # Keep malformed, untrusted bundles on the structured-error path.
        errors = [f"bundle validation failed: {type(exc).__name__}: {exc}"]
    result = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("PASS" if not errors else "FAIL")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
