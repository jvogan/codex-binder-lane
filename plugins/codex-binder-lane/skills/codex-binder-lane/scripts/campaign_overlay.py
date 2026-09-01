#!/usr/bin/env python3
"""Import and verify one immutable, provider-neutral companion stage receipt.

This module is deliberately an evidence importer, not an executor.  It never
contacts a provider, starts a job, resumes a job, or changes the base campaign
packet.  A completed companion receipt can establish only a hash-bound
``transport-proven`` overlay; it cannot establish scientific validity.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import campaign_packet  # noqa: E402
import strict_json  # noqa: E402
import validate_plan  # noqa: E402
import validate_qualification  # noqa: E402


OVERLAY_MANIFEST_SCHEMA = "codex-binder-companion-overlay-manifest/v1"
OVERLAY_ID_SCHEMA = "codex-binder-companion-overlay-id/v1"
OVERLAY_STATUS_SCHEMA = "codex-binder-companion-overlay-status/v1"
RECEIPT_SCHEMA = "codex-binder-companion-stage-receipt/v1"
MANIFEST_PATH = "overlay-manifest.json"
MANIFEST_SHA_PATH = "overlay-manifest.sha256"
RECEIPT_PATH = "receipts/companion-stage-receipt.json"
STATUS_PATH = "overlay-status.json"
ARTIFACT_PREFIX = "artifacts/"
MAX_OVERLAY_FILES = 32
MAX_OVERLAY_BYTES = 640 * 1024 * 1024
MAX_RECEIPT_INPUTS = campaign_packet.MAX_PACKET_FILES
MAX_RECEIPT_OUTPUTS = MAX_OVERLAY_FILES - 2
MAX_TEXT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = campaign_packet.MAX_JSON_BYTES
MAX_ARTIFACT_BYTES = campaign_packet.MAX_ARTIFACT_BYTES
HARD_MAX_OVERLAY_FILES = validate_plan.MAX_OVERLAY_OUTPUT_FILES + 2
HARD_MAX_OVERLAY_BYTES = validate_plan.MAX_OVERLAY_OUTPUT_BYTES
HARD_MAX_ARTIFACT_BYTES = validate_plan.MAX_OVERLAY_ARTIFACT_BYTES
SHA256_RE = campaign_packet.SHA256_RE
CLAIM_RANK = {
    "plan-only": 0,
    "transport-proven": 1,
}
RECEIPT_KEYS = {
    "schema_version",
    "receipt_id",
    "campaign_id",
    "base_packet_id",
    "base_manifest_sha256",
    "stage_id",
    "capability",
    "route_kind",
    "provider",
    "execution_state",
    "provider_request_id",
    "inputs",
    "outputs",
    "cost",
    "cleanup_state",
    "claim_ceiling",
}
IDENTITY_KEYS = {"id", "revision"}
ARTIFACT_KEYS = {"path", "sha256", "size_bytes"}
COST_KEYS = {"status", "estimate_usd", "observed_usd"}
EXECUTION_STATES = {"completed", "failed"}
CLEANUP_STATES = {"not-applicable", "pending", "verified", "failed"}
COST_STATES = {"unknown", "estimated", "observed", "not-applicable"}
TEXT_OUTPUT_SUFFIXES = {
    ".a3m",
    ".cif",
    ".csv",
    ".fa",
    ".faa",
    ".fasta",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".mmcif",
    ".pdb",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+")
FIELD_ASSIGNMENT_RE = re.compile(
    r"^\s*[\"']?([A-Za-z0-9_.-]+)[\"']?\s*[:=]\s*(.*?)\s*,?\s*$"
)
REDACTED_VALUES = {"", "null", "none", "redacted", "placeholder", "unknown"}
WINDOWS_FORBIDDEN_COMPONENT_RE = re.compile(r'[<>:"|?*]')
WINDOWS_RESERVED_BASE_RE = re.compile(
    r"^(?:con|prn|aux|nul|conin\$|conout\$|com[1-9¹²³]|lpt[1-9¹²³])$",
    re.IGNORECASE,
)


class OverlayError(ValueError):
    """Carry one or more user-correctable companion-overlay errors."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else errors
        super().__init__(self.errors[0] if self.errors else "companion overlay failed")


class DuplicateKeyError(ValueError):
    """Reject ambiguous JSON before exact receipt bytes are retained."""


def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_strict_json_object(data: bytes, context: str) -> dict[str, Any]:
    try:
        value = strict_json.loads(data)
    except strict_json.StrictJSONError as exc:
        raise OverlayError(f"{context}: invalid or ambiguous JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise OverlayError(f"{context}: JSON root must be an object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return campaign_packet.canonical_json_bytes(value)


def sha256_bytes(value: bytes) -> str:
    return campaign_packet.sha256_bytes(value)


def artifact_ref(path: str, payloads: dict[str, bytes]) -> dict[str, Any]:
    return campaign_packet.artifact_ref(path, payloads)


def nonnegative_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and value >= 0
    )


def exact_object(
    value: Any,
    context: str,
    keys: set[str],
    errors: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return {}
    missing = sorted(keys - set(value))
    extra = sorted(set(value) - keys)
    if missing:
        errors.append(f"{context} is missing required keys: {', '.join(missing)}")
    if extra:
        errors.append(f"{context} contains unsupported keys: {', '.join(extra)}")
    return value


def check_identifier(value: Any, context: str, errors: list[str], *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not validate_qualification.portable_identifier(value):
        qualifier = "a portable identifier or null" if nullable else "a portable identifier"
        errors.append(f"{context} must be {qualifier}")


def check_identity(value: Any, context: str, errors: list[str]) -> dict[str, Any]:
    identity = exact_object(value, context, IDENTITY_KEYS, errors)
    for field in sorted(IDENTITY_KEYS):
        check_identifier(identity.get(field), f"{context}.{field}", errors)
    return identity


def check_artifact_ref(
    value: Any,
    context: str,
    errors: list[str],
    *,
    maximum_bytes: int = MAX_ARTIFACT_BYTES,
) -> dict[str, Any]:
    reference = exact_object(value, context, ARTIFACT_KEYS, errors)
    path = reference.get("path")
    if not campaign_packet.safe_relative_path(path):
        errors.append(f"{context}.path must be a safe relative POSIX path")
    digest = reference.get("sha256")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        errors.append(f"{context}.sha256 must be a lowercase SHA-256")
    size = reference.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        errors.append(f"{context}.size_bytes must be a non-negative integer")
    elif size > maximum_bytes:
        errors.append(f"{context}.size_bytes exceeds the {maximum_bytes}-byte per-artifact limit")
    return reference


def portable_output_path(value: str) -> bool:
    for component in PurePosixPath(value).parts:
        windows_base = component.split(".", 1)[0].rstrip(" .")
        if (
            component.endswith((" ", "."))
            or WINDOWS_FORBIDDEN_COMPONENT_RE.search(component) is not None
            or WINDOWS_RESERVED_BASE_RE.fullmatch(windows_base) is not None
        ):
            return False
    return True


def check_artifact_list(
    value: Any,
    context: str,
    errors: list[str],
    *,
    allow_empty: bool,
    require_output_prefix: bool,
    max_items: int,
    maximum_bytes: int = MAX_ARTIFACT_BYTES,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{context} must be an array")
        return []
    if not allow_empty and not value:
        errors.append(f"{context} must be a non-empty array")
    if len(value) > max_items:
        errors.append(
            f"{context} must contain at most {max_items} entries before path validation"
        )
        return []
    references: list[dict[str, Any]] = []
    paths: list[str] = []
    for index, item in enumerate(value):
        reference = check_artifact_ref(
            item, f"{context}[{index}]", errors, maximum_bytes=maximum_bytes
        )
        references.append(reference)
        path = reference.get("path")
        if isinstance(path, str):
            paths.append(path)
            if require_output_prefix and not path.startswith(ARTIFACT_PREFIX):
                errors.append(f"{context}[{index}].path must begin with {ARTIFACT_PREFIX}")
            if require_output_prefix and not portable_output_path(path):
                errors.append(
                    f"{context}[{index}].path must use portable cross-platform components"
                )
    if paths != sorted(paths):
        errors.append(f"{context} paths must be lexically sorted")
    if len(paths) != len(set(paths)):
        errors.append(f"{context} paths must be unique")
    portable_keys = [unicodedata.normalize("NFC", path).casefold() for path in paths]
    if len(portable_keys) != len(set(portable_keys)):
        errors.append(
            f"{context} paths must remain unique after Unicode normalization and case-folding"
        )
    collision = campaign_packet.prefix_collision(set(paths))
    if collision is not None:
        errors.append(
            f"{context} paths collide as a file and directory: {collision[0]} and {collision[1]}"
        )
    portable_collision = campaign_packet.prefix_collision(set(portable_keys))
    if portable_collision is not None:
        errors.append(
            f"{context} paths collide after Unicode normalization and case-folding: "
            f"{portable_collision[0]} and {portable_collision[1]}"
        )
    return references


def check_cost(value: Any, errors: list[str]) -> dict[str, Any]:
    cost = exact_object(value, "receipt.cost", COST_KEYS, errors)
    status = cost.get("status")
    if status not in COST_STATES:
        errors.append("receipt.cost.status must be unknown, estimated, observed, or not-applicable")
    for field in ("estimate_usd", "observed_usd"):
        amount = cost.get(field)
        if amount is not None and not nonnegative_number(amount):
            errors.append(f"receipt.cost.{field} must be a non-negative number or null")
    if status in {"unknown", "not-applicable"} and (
        cost.get("estimate_usd") is not None or cost.get("observed_usd") is not None
    ):
        errors.append(f"receipt.cost.{status} requires null estimate_usd and observed_usd")
    if status == "estimated" and (
        not nonnegative_number(cost.get("estimate_usd")) or cost.get("observed_usd") is not None
    ):
        errors.append("receipt.cost.estimated requires estimate_usd and null observed_usd")
    if status == "observed" and not nonnegative_number(cost.get("observed_usd")):
        errors.append("receipt.cost.observed requires observed_usd")
    return cost


def declared_overlay_ceiling(base: dict[str, Any]) -> str:
    plan_evidence = base["plan"].get("evidence")
    plan_ceiling = plan_evidence.get("claim_ceiling") if isinstance(plan_evidence, dict) else None
    target_ceiling = base["target"].get("claim_ceiling")
    ceilings = ["transport-proven"]
    for value in (plan_ceiling, target_ceiling):
        if value in campaign_packet.CLAIM_RANK:
            ceilings.append(value)
    return min(ceilings, key=campaign_packet.CLAIM_RANK.__getitem__)


def overlay_limits(base: dict[str, Any]) -> dict[str, int]:
    """Resolve frozen, validated per-overlay budgets with conservative v1 defaults."""
    configured = base["plan"].get("execution", {}).get("artifact_budget")
    if not isinstance(configured, dict):
        return {
            "output_files": MAX_RECEIPT_OUTPUTS,
            "overlay_files": MAX_OVERLAY_FILES,
            "overlay_bytes": MAX_OVERLAY_BYTES,
            "artifact_bytes": MAX_ARTIFACT_BYTES,
        }
    output_files = int(configured["max_output_files_per_overlay"])
    overlay_bytes = int(configured["max_output_bytes_per_overlay"])
    artifact_bytes = int(configured["max_output_bytes_per_artifact"])
    if (
        output_files > HARD_MAX_OVERLAY_FILES - 2
        or overlay_bytes > HARD_MAX_OVERLAY_BYTES
        or artifact_bytes > HARD_MAX_ARTIFACT_BYTES
    ):
        raise OverlayError("frozen plan artifact budget exceeds importer hard safety bounds")
    return {
        "output_files": output_files,
        "overlay_files": output_files + 2,
        "overlay_bytes": overlay_bytes,
        "artifact_bytes": artifact_bytes,
    }


def stage_by_id(base: dict[str, Any], stage_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    stages = base["plan"].get("execution", {}).get("stages", [])
    plan_matches = [
        stage
        for stage in stages
        if isinstance(stage, dict) and campaign_packet.plan_stage_id(stage) == stage_id
    ]
    qualified = base["qualification"].get("stages", [])
    qualification_matches = [
        stage
        for stage in qualified
        if isinstance(stage, dict) and stage.get("stage_id") == stage_id
    ]
    return (
        plan_matches[0] if len(plan_matches) == 1 else None,
        qualification_matches[0] if len(qualification_matches) == 1 else None,
    )


def validate_receipt(receipt: Any, base: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    item = exact_object(receipt, "receipt", RECEIPT_KEYS, errors)
    if not isinstance(receipt, dict):
        raise OverlayError(errors)

    if item.get("schema_version") != RECEIPT_SCHEMA:
        errors.append(f"receipt.schema_version must equal {RECEIPT_SCHEMA}")
    for field in ("receipt_id", "campaign_id", "stage_id", "provider"):
        check_identifier(item.get(field), f"receipt.{field}", errors)
    if item.get("base_packet_id") != base["packet_id"]:
        errors.append("receipt.base_packet_id must match the verified base packet")
    manifest_sha = item.get("base_manifest_sha256")
    if not isinstance(manifest_sha, str) or SHA256_RE.fullmatch(manifest_sha) is None:
        errors.append("receipt.base_manifest_sha256 must be a lowercase SHA-256")
    elif manifest_sha != base["manifest_sha256"]:
        errors.append("receipt.base_manifest_sha256 must match the verified base manifest")
    if item.get("campaign_id") != base["campaign_id"]:
        errors.append("receipt.campaign_id must match the verified base packet")

    capability = check_identity(item.get("capability"), "receipt.capability", errors)
    route_kind = item.get("route_kind")
    if route_kind not in validate_qualification.ROUTE_KINDS - {"unbound"}:
        errors.append("receipt.route_kind must be one qualified, bound route kind")
    request_id = item.get("provider_request_id")
    check_identifier(request_id, "receipt.provider_request_id", errors, nullable=True)
    execution_state = item.get("execution_state")
    if execution_state not in EXECUTION_STATES:
        errors.append("receipt.execution_state must be completed or failed")
    cleanup_state = item.get("cleanup_state")
    if cleanup_state not in CLEANUP_STATES:
        errors.append("receipt.cleanup_state must be not-applicable, pending, verified, or failed")
    claim_ceiling = item.get("claim_ceiling")
    if claim_ceiling not in CLAIM_RANK:
        errors.append("receipt.claim_ceiling must be plan-only or transport-proven")
    elif CLAIM_RANK[claim_ceiling] > CLAIM_RANK[declared_overlay_ceiling(base)]:
        errors.append("receipt.claim_ceiling exceeds the plan/target transport authorization ceiling")
    cost = check_cost(item.get("cost"), errors)

    limits = overlay_limits(base)
    inputs = check_artifact_list(
        item.get("inputs"),
        "receipt.inputs",
        errors,
        allow_empty=False,
        require_output_prefix=False,
        max_items=MAX_RECEIPT_INPUTS,
    )
    outputs = check_artifact_list(
        item.get("outputs"),
        "receipt.outputs",
        errors,
        allow_empty=True,
        require_output_prefix=True,
        max_items=limits["output_files"],
        maximum_bytes=limits["artifact_bytes"],
    )
    input_paths = {reference.get("path") for reference in inputs if isinstance(reference.get("path"), str)}
    known_inputs = base["manifest_by_path"]
    for reference in inputs:
        path = reference.get("path")
        if isinstance(path, str) and known_inputs.get(path) != reference:
            errors.append(f"receipt.inputs reference is not an exact base manifest artifact: {path}")
    if len(input_paths) != len(inputs):
        errors.append("receipt.inputs must contain valid, distinct artifact references")

    plan_stage, qualified_stage = stage_by_id(base, item.get("stage_id"))
    if plan_stage is None or qualified_stage is None:
        errors.append("receipt.stage_id must identify exactly one plan and qualification stage")
    else:
        if capability != qualified_stage.get("capability"):
            errors.append("receipt.capability must match the qualified stage capability")
        if item.get("route_kind") != plan_stage.get("route_kind"):
            errors.append("receipt.route_kind must match the frozen plan stage route")
        if item.get("route_kind") != qualified_stage.get("route_kind"):
            errors.append("receipt.route_kind must match the qualified stage route")
        if item.get("provider") != plan_stage.get("provider"):
            errors.append("receipt.provider must match the frozen plan stage provider")
        if item.get("provider") != qualified_stage.get("provider"):
            errors.append("receipt.provider must match the qualified stage provider")
        plan_estimate = plan_stage.get("estimated_cost_usd")
        qualified_price = qualified_stage.get("price")
        qualified_estimate = (
            qualified_price.get("estimate_usd") if isinstance(qualified_price, dict) else None
        )
        receipt_estimate = cost.get("estimate_usd")
        if receipt_estimate is not None and (
            receipt_estimate != plan_estimate or receipt_estimate != qualified_estimate
        ):
            errors.append(
                "receipt.cost.estimate_usd must match the frozen plan and qualification estimates"
            )
        if cost.get("status") == "estimated" and receipt_estimate is None:
            errors.append("estimated receipt cost must bind the frozen estimate")
        paid_stage = plan_stage.get("paid") is True or (
            nonnegative_number(plan_estimate) and plan_estimate > 0
        )
        if paid_stage and cost.get("status") == "not-applicable":
            errors.append("paid stages cannot report cost as not-applicable")

    if execution_state == "completed":
        if base["plan"].get("mode") != "execute":
            errors.append("completed receipts require the frozen plan mode to be execute")
        if base["qualification"].get("mode") != "execute":
            errors.append(
                "completed receipts require the frozen qualification mode to be execute"
            )
        if not outputs:
            errors.append("completed receipts must declare at least one output artifact")
        if claim_ceiling != "transport-proven":
            errors.append("completed receipts must use the transport-proven claim ceiling")
        if route_kind in validate_qualification.REMOTE_ROUTE_KINDS and request_id is None:
            errors.append("completed remote receipts require a provider_request_id")
        if cleanup_state not in {"not-applicable", "verified"}:
            errors.append(
                "completed receipts require a terminal cleanup_state: "
                "not-applicable or verified"
            )
    elif execution_state == "failed":
        if outputs:
            errors.append("failed receipts must not declare output artifacts")
        if claim_ceiling != "plan-only":
            errors.append("failed receipts must use the plan-only claim ceiling")

    errors.extend(f"receipt: {finding}" for finding in validate_qualification.secret_findings(item))
    if errors:
        raise OverlayError(errors)
    return item


def load_base_packet(packet: Path) -> dict[str, Any]:
    verification = campaign_packet.verify_packet(packet)
    if verification.get("dispatch_eligible") is not False or verification.get("claim_ceiling") != "plan-only":
        raise OverlayError("base packet must remain immutable, dispatch-disabled, and plan-only")
    manifest_bytes = campaign_packet.read_relative_regular(
        packet,
        campaign_packet.MANIFEST_PATH,
        "base packet manifest",
        maximum_bytes=MAX_JSON_BYTES,
    )
    manifest = campaign_packet.parse_json_object(manifest_bytes, "base packet manifest")
    plan_bytes = campaign_packet.read_relative_regular(
        packet,
        campaign_packet.PLAN_PATH,
        "base packet plan",
        maximum_bytes=MAX_JSON_BYTES,
    )
    plan = campaign_packet.parse_json_object(plan_bytes, "base packet plan")
    lock_reference = campaign_packet.target_lock_ref(plan)
    lock_path = lock_reference.get("path") if isinstance(lock_reference, dict) else None
    if not campaign_packet.safe_relative_path(lock_path):
        raise OverlayError("verified base packet does not expose a safe target lock path")
    target_bytes = campaign_packet.read_relative_regular(
        packet,
        lock_path,
        "base packet target lock",
        maximum_bytes=MAX_JSON_BYTES,
    )
    target = campaign_packet.parse_json_object(target_bytes, "base packet target lock")
    qualification_bytes = campaign_packet.read_relative_regular(
        packet,
        campaign_packet.QUALIFICATION_PATH,
        "base packet qualification ledger",
        maximum_bytes=MAX_JSON_BYTES,
    )
    qualification = campaign_packet.parse_json_object(
        qualification_bytes, "base packet qualification ledger"
    )
    manifest_by_path = {reference["path"]: reference for reference in manifest["files"]}
    return {
        "packet": packet,
        "packet_id": verification["packet_id"],
        "manifest_sha256": verification["manifest_sha256"],
        "campaign_id": plan["campaign_id"],
        "plan": plan,
        "target": target,
        "qualification": qualification,
        "manifest_by_path": manifest_by_path,
    }


def load_output_payloads(
    receipt: dict[str, Any], artifact_root: Path, *, maximum_bytes: int
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for reference in receipt["outputs"]:
        path = reference["path"]
        data = campaign_packet.read_relative_regular(
            artifact_root,
            path,
            f"companion output {path}",
            maximum_bytes=maximum_bytes,
        )
        if len(data) != reference["size_bytes"] or sha256_bytes(data) != reference["sha256"]:
            raise OverlayError(f"companion output {path}: receipt hash or byte count changed")
        scan_output_payload(path, data)
        payloads[path] = data
    return payloads


def parsed_output_json(text: str, context: str) -> Any:
    try:
        return strict_json.loads(text)
    except strict_json.StrictJSONError as exc:
        raise OverlayError(f"{context}: invalid or ambiguous JSON: {exc}") from exc


def scan_output_payload(path: str, data: bytes) -> None:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in TEXT_OUTPUT_SUFFIXES:
        return
    if len(data) > MAX_TEXT_OUTPUT_BYTES:
        raise OverlayError(
            f"companion output {path}: inspectable text exceeds the "
            f"{MAX_TEXT_OUTPUT_BYTES}-byte safety limit"
        )
    if b"\x00" in data:
        raise OverlayError(f"companion output {path}: text artifact contains NUL bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OverlayError(f"companion output {path}: text artifact must be UTF-8") from exc
    findings = validate_qualification.secret_findings(text, f"output[{path}]")
    for index, match in enumerate(URL_RE.finditer(text)):
        findings.extend(
            validate_qualification.secret_findings(
                match.group(0).rstrip(".,;:)"), f"output[{path}].url[{index}]"
            )
        )
    if suffix == ".json":
        findings.extend(
            validate_qualification.secret_findings(
                parsed_output_json(text, f"companion output {path}"), f"output[{path}]"
            )
        )
    elif suffix == ".jsonl":
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                findings.extend(
                    validate_qualification.secret_findings(
                        parsed_output_json(line, f"companion output {path}:{line_number}"),
                        f"output[{path}][{line_number}]",
                    )
                )
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = FIELD_ASSIGNMENT_RE.fullmatch(line)
        if match is None:
            continue
        normalized_key = match.group(1).lower().replace("-", "_")
        normalized_value = match.group(2).strip().strip(",}").strip("\"'").lower()
        if (
            validate_qualification.SECRET_KEY_RE.search(normalized_key)
            and normalized_value not in REDACTED_VALUES
        ):
            findings.append(
                f"output[{path}]:{line_number} contains a credential-like field"
            )
    if findings:
        raise OverlayError(
            f"companion output {path}: sensitive text rejected: {', '.join(sorted(set(findings)))}"
        )


def overlay_id_for(
    base: dict[str, Any], receipt_bytes: bytes, output_payloads: dict[str, bytes]
) -> str:
    identity = {
        "schema_version": OVERLAY_ID_SCHEMA,
        "base_packet_id": base["packet_id"],
        "base_manifest_sha256": base["manifest_sha256"],
        "receipt": {
            "path": RECEIPT_PATH,
            "sha256": sha256_bytes(receipt_bytes),
            "size_bytes": len(receipt_bytes),
        },
        "outputs": [artifact_ref(path, output_payloads) for path in sorted(output_payloads)],
    }
    return sha256_bytes(canonical_json_bytes(identity))


def build_status(
    base: dict[str, Any], receipt: dict[str, Any], overlay_id: str
) -> dict[str, Any]:
    observed = receipt["cost"].get("observed_usd")
    maximum_spend = base["plan"].get("budget", {}).get("maximum_spend_usd")
    observed_over_ceiling = (
        nonnegative_number(observed)
        and nonnegative_number(maximum_spend)
        and observed > maximum_spend
    )
    return {
        "schema_version": OVERLAY_STATUS_SCHEMA,
        "campaign_id": base["campaign_id"],
        "base_packet_id": base["packet_id"],
        "base_manifest_sha256": base["manifest_sha256"],
        "overlay_id": overlay_id,
        "receipt_id": receipt["receipt_id"],
        "stage_id": receipt["stage_id"],
        "execution_state": receipt["execution_state"],
        "claim_ceiling": receipt["claim_ceiling"],
        "base_packet_claim_ceiling": "plan-only",
        "base_packet_dispatch_eligible": False,
        "dispatch_attempted": False,
        "network_used_by_importer": False,
        "provider_execution_verified_by_importer": False,
        "cleanup_state_reported": receipt["cleanup_state"],
        "cost_status_reported": receipt["cost"]["status"],
        "cost_estimate_usd_reported": receipt["cost"].get("estimate_usd"),
        "cost_observed_usd_reported": observed,
        "campaign_maximum_spend_usd": maximum_spend,
        "observed_cost_over_campaign_ceiling": observed_over_ceiling,
        "output_count": len(receipt["outputs"]),
    }


def preflight_declared_resources(
    base: dict[str, Any], receipt_bytes: bytes, receipt: dict[str, Any]
) -> None:
    limits = overlay_limits(base)
    output_count = len(receipt["outputs"])
    if output_count + 2 > limits["overlay_files"]:
        raise OverlayError(
            f"overlay exceeds the {limits['overlay_files']}-payload-file limit before artifact reads"
        )
    status_bytes = canonical_json_bytes(build_status(base, receipt, "0" * 64))
    declared_total = (
        len(receipt_bytes)
        + len(status_bytes)
        + sum(reference["size_bytes"] for reference in receipt["outputs"])
    )
    if declared_total > limits["overlay_bytes"]:
        raise OverlayError(
            f"overlay exceeds the {limits['overlay_bytes']}-byte aggregate limit before artifact reads"
        )


def build_overlay_payloads(
    base: dict[str, Any],
    receipt_bytes: bytes,
    receipt: dict[str, Any],
    output_payloads: dict[str, bytes],
) -> tuple[dict[str, bytes], str]:
    limits = overlay_limits(base)
    output_paths = {reference["path"] for reference in receipt["outputs"]}
    if set(output_payloads) != output_paths:
        raise OverlayError("companion output payload set does not match the receipt")
    overlay_id = overlay_id_for(base, receipt_bytes, output_payloads)
    payloads = {
        RECEIPT_PATH: receipt_bytes,
        STATUS_PATH: canonical_json_bytes(build_status(base, receipt, overlay_id)),
        **output_payloads,
    }
    if len(payloads) > limits["overlay_files"]:
        raise OverlayError(f"overlay exceeds the {limits['overlay_files']}-file limit")
    total = sum(len(data) for data in payloads.values())
    if total > limits["overlay_bytes"]:
        raise OverlayError(f"overlay exceeds the {limits['overlay_bytes']}-byte aggregate limit")
    return payloads, overlay_id


def build_manifest(base: dict[str, Any], receipt: dict[str, Any], payloads: dict[str, bytes], overlay_id: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": OVERLAY_MANIFEST_SCHEMA,
            "campaign_id": base["campaign_id"],
            "base_packet_id": base["packet_id"],
            "base_manifest_sha256": base["manifest_sha256"],
            "overlay_id": overlay_id,
            "receipt_id": receipt["receipt_id"],
            "files": [artifact_ref(path, payloads) for path in sorted(payloads)],
        }
    )


def write_overlay(
    destination: Path,
    payloads: dict[str, bytes],
    manifest_bytes: bytes,
    *,
    pre_rename_verify: Callable[[Path], None],
) -> None:
    if destination.exists() or destination.is_symlink():
        raise OverlayError("output directory already exists; choose a new overlay path")
    try:
        campaign_packet.validate_output_parent(destination)
    except campaign_packet.PacketError as exc:
        raise OverlayError(exc.errors) from exc
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        for relative_path, data in sorted(payloads.items()):
            output = temporary / relative_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        (temporary / MANIFEST_PATH).write_bytes(manifest_bytes)
        (temporary / MANIFEST_SHA_PATH).write_text(
            f"{sha256_bytes(manifest_bytes)}  overlay-manifest.json\n", encoding="ascii"
        )
        pre_rename_verify(temporary)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def resolved_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError as exc:
        raise OverlayError(f"cannot resolve path {path}: {exc}") from exc


def require_disjoint_trees(base_packet: Path, destination: Path) -> None:
    base = resolved_path(base_packet)
    output = resolved_path(destination)
    if output == base or output.is_relative_to(base) or base.is_relative_to(output):
        raise OverlayError("overlay output and base packet must be disjoint path trees")


def overlay_tree_files(overlay: Path) -> set[str]:
    def fail_walk(error: OSError) -> None:
        raise OverlayError(f"overlay tree traversal failed: {error}") from error

    files: set[str] = set()
    for current, directories, names in os.walk(
        overlay, followlinks=False, onerror=fail_walk
    ):
        current_path = Path(current)
        for name in [*directories, *names]:
            path = current_path / name
            if path.is_symlink():
                relative = path.relative_to(overlay).as_posix()
                raise OverlayError(f"overlay contains a forbidden symlink: {relative}")
        files.update(
            (current_path / name).relative_to(overlay).as_posix() for name in names
        )
    return files


def read_overlay_manifest(
    overlay: Path, base: dict[str, Any]
) -> tuple[bytes, dict[str, Any], dict[str, bytes]]:
    limits = overlay_limits(base)
    try:
        mode = overlay.lstat().st_mode
    except OSError as exc:
        raise OverlayError(f"overlay: cannot inspect directory: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise OverlayError("overlay path must be a non-symlink directory")
    manifest_bytes = campaign_packet.read_relative_regular(
        overlay, MANIFEST_PATH, "overlay manifest", maximum_bytes=MAX_JSON_BYTES
    )
    manifest = campaign_packet.parse_json_object(manifest_bytes, "overlay manifest")
    sidecar = campaign_packet.read_relative_regular(
        overlay, MANIFEST_SHA_PATH, "overlay manifest sidecar", maximum_bytes=1024
    )
    expected_sidecar = f"{sha256_bytes(manifest_bytes)}  overlay-manifest.json\n".encode("ascii")
    if sidecar != expected_sidecar:
        raise OverlayError("overlay manifest sidecar does not match the manifest bytes")
    manifest_keys = {
        "schema_version",
        "campaign_id",
        "base_packet_id",
        "base_manifest_sha256",
        "overlay_id",
        "receipt_id",
        "files",
    }
    if set(manifest) != manifest_keys:
        raise OverlayError("overlay manifest contains unsupported or missing fields")
    if manifest.get("schema_version") != OVERLAY_MANIFEST_SCHEMA:
        raise OverlayError(f"overlay manifest schema must equal {OVERLAY_MANIFEST_SCHEMA}")
    for field in ("campaign_id", "receipt_id"):
        if not validate_qualification.portable_identifier(manifest.get(field)):
            raise OverlayError(f"overlay manifest {field} must be a portable identifier")
    for field in ("base_packet_id", "base_manifest_sha256", "overlay_id"):
        value = manifest.get(field)
        if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
            raise OverlayError(f"overlay manifest {field} must be a lowercase SHA-256")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise OverlayError("overlay manifest files must be a non-empty array")
    if len(files) > limits["overlay_files"]:
        raise OverlayError(f"overlay manifest exceeds the {limits['overlay_files']}-file limit")
    errors: list[str] = []
    references = check_artifact_list(
        files,
        "overlay manifest files",
        errors,
        allow_empty=False,
        require_output_prefix=False,
        max_items=limits["overlay_files"],
        maximum_bytes=limits["artifact_bytes"],
    )
    if errors:
        raise OverlayError(errors)
    paths = [reference["path"] for reference in references]
    payloads: dict[str, bytes] = {}
    total = 0
    for reference in references:
        data = campaign_packet.read_relative_regular(
            overlay,
            reference["path"],
            f"overlay payload {reference['path']}",
            maximum_bytes=limits["artifact_bytes"],
        )
        if len(data) != reference["size_bytes"] or sha256_bytes(data) != reference["sha256"]:
            raise OverlayError(
                f"overlay payload {reference['path']}: manifest hash or byte count mismatch"
            )
        total += len(data)
        if total > limits["overlay_bytes"]:
            raise OverlayError(
                f"overlay manifest exceeds the {limits['overlay_bytes']}-byte aggregate limit"
            )
        payloads[reference["path"]] = data
    expected_files = set(paths) | {MANIFEST_PATH, MANIFEST_SHA_PATH}
    actual_files = overlay_tree_files(overlay)
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"undeclared: {', '.join(extra)}")
        raise OverlayError(f"overlay file set differs from the manifest ({'; '.join(details)})")
    return manifest_bytes, manifest, payloads


def import_stage(
    base_packet: Path,
    receipt_path: Path,
    destination: Path,
    artifact_root: Path,
) -> dict[str, Any]:
    require_disjoint_trees(base_packet, destination)
    base = load_base_packet(base_packet)
    receipt_bytes = campaign_packet.read_regular(
        receipt_path, "companion receipt", maximum_bytes=MAX_JSON_BYTES
    )
    receipt = parse_strict_json_object(receipt_bytes, "companion receipt")
    receipt = validate_receipt(receipt, base)
    preflight_declared_resources(base, receipt_bytes, receipt)
    output_payloads = load_output_payloads(
        receipt, artifact_root, maximum_bytes=overlay_limits(base)["artifact_bytes"]
    )
    payloads, overlay_id = build_overlay_payloads(base, receipt_bytes, receipt, output_payloads)
    manifest_bytes = build_manifest(base, receipt, payloads, overlay_id)
    write_overlay(
        destination,
        payloads,
        manifest_bytes,
        pre_rename_verify=lambda staged: verify_overlay(base_packet, staged),
    )
    return {
        "ok": True,
        "operation": "import-stage",
        "overlay": str(destination),
        "overlay_id": overlay_id,
        "base_packet_id": base["packet_id"],
        "base_manifest_sha256": base["manifest_sha256"],
        "receipt_id": receipt["receipt_id"],
        "stage_id": receipt["stage_id"],
        "execution_state": receipt["execution_state"],
        "claim_ceiling": receipt["claim_ceiling"],
        "output_count": len(receipt["outputs"]),
        "dispatch_attempted": False,
        "network_used_by_importer": False,
        "provider_execution_verified_by_importer": False,
    }


def verify_overlay(base_packet: Path, overlay: Path) -> dict[str, Any]:
    base = load_base_packet(base_packet)
    manifest_bytes, manifest, payloads = read_overlay_manifest(overlay, base)
    if RECEIPT_PATH not in payloads or STATUS_PATH not in payloads:
        raise OverlayError("overlay must contain the companion receipt and derived status")
    receipt = parse_strict_json_object(
        payloads[RECEIPT_PATH], "overlay companion receipt"
    )
    receipt = validate_receipt(receipt, base)
    output_payloads: dict[str, bytes] = {}
    for reference in receipt["outputs"]:
        path = reference["path"]
        data = payloads.get(path)
        if data is None:
            raise OverlayError(f"overlay is missing receipt-declared output: {path}")
        if len(data) != reference["size_bytes"] or sha256_bytes(data) != reference["sha256"]:
            raise OverlayError(f"overlay output {path}: receipt hash or byte count mismatch")
        scan_output_payload(path, data)
        output_payloads[path] = data
    expected_payloads, overlay_id = build_overlay_payloads(
        base, payloads[RECEIPT_PATH], receipt, output_payloads
    )
    if set(payloads) != set(expected_payloads):
        raise OverlayError("overlay payload set does not match the single-stage receipt contract")
    for path, expected in expected_payloads.items():
        if payloads[path] != expected:
            raise OverlayError(f"overlay payload {path} differs from deterministic output")
    expected_manifest = build_manifest(base, receipt, expected_payloads, overlay_id)
    if manifest_bytes != expected_manifest:
        raise OverlayError("overlay manifest differs from deterministic output")
    return {
        "ok": True,
        "operation": "verify",
        "overlay": str(overlay),
        "overlay_valid": True,
        "overlay_id": overlay_id,
        "base_packet_id": base["packet_id"],
        "base_manifest_sha256": base["manifest_sha256"],
        "receipt_id": receipt["receipt_id"],
        "stage_id": receipt["stage_id"],
        "execution_state": receipt["execution_state"],
        "claim_ceiling": receipt["claim_ceiling"],
        "output_count": len(receipt["outputs"]),
        "dispatch_attempted": False,
        "network_used_by_importer": False,
        "provider_execution_verified_by_importer": False,
    }


def print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if result.get("operation") == "import-stage":
        print(f"Companion receipt overlay imported: {result['overlay']}")
    else:
        print("Companion receipt overlay is valid.")
    print("No provider call, dispatch, or base-packet mutation was performed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import-stage")
    import_parser.add_argument("base_packet", type=Path)
    import_parser.add_argument("receipt", type=Path)
    import_parser.add_argument("output", type=Path)
    import_parser.add_argument("--artifact-root", type=Path, required=True)
    import_parser.add_argument("--json", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("base_packet", type=Path)
    verify_parser.add_argument("overlay", type=Path)
    verify_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "import-stage":
            result = import_stage(args.base_packet, args.receipt, args.output, args.artifact_root)
        else:
            result = verify_overlay(args.base_packet, args.overlay)
    except (OverlayError, campaign_packet.PacketError) as exc:
        result = {"ok": False, "operation": args.command, "errors": exc.errors}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for error in exc.errors:
                print(f"ERROR: {error}")
        return 1
    except Exception as exc:  # Keep untrusted inputs and filesystem failures structured.
        message = f"companion overlay operation failed: {type(exc).__name__}: {exc}"
        result = {"ok": False, "operation": args.command, "errors": [message]}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {message}")
        return 1
    print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
