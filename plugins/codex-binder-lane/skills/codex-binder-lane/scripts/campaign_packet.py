#!/usr/bin/env python3
"""Materialize and verify a local Binder Lane campaign packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import validate_plan  # noqa: E402
import validate_qualification  # noqa: E402
import validate_target_site  # noqa: E402
import strict_json  # noqa: E402


PACKET_MANIFEST_SCHEMA = "codex-binder-campaign-packet-manifest/v1"
PACKET_ID_SCHEMA = "codex-binder-campaign-packet-id/v1"
GRAPH_SCHEMA = "codex-binder-campaign-graph/v1"
STATUS_SCHEMA = "codex-binder-campaign-status/v1"
RECEIPT_SCHEMA = "codex-binder-campaign-materialization-receipt/v1"
MANIFEST_PATH = "campaign/packet-manifest.json"
MANIFEST_SHA_PATH = "campaign/packet-manifest.sha256"
PLAN_PATH = "codex-binder-plan.json"
QUALIFICATION_PATH = "qualification/qualification-ledger.json"
GRAPH_PATH = "campaign/stage-graph.json"
STATUS_PATH = "campaign/status.json"
REPORT_PATH = "campaign/report.md"
RECEIPT_PATH = "campaign/materialization-receipt.json"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_PACKET_BYTES = 640 * 1024 * 1024
MAX_PACKET_FILES = 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SYSTEM_SYMLINK_ALIASES = {
    Path("/").joinpath(name) for name in ("etc", "tmp", "var")
}
CLAIM_RANK = {
    "plan-only": 0,
    "transport-proven": 1,
    "computational-candidate": 2,
    "cross-model-supported": 3,
}
QUALIFICATION_RANK = {
    state: index for index, state in enumerate(validate_qualification.EVIDENCE_STATES)
}
MATERIALIZER_CLAIM_CEILING = "plan-only"
EVIDENCE_LINKAGE_BLOCKER = (
    "qualification schema v1 does not bind supporting evidence references; dispatch remains disabled"
)


class PacketError(ValueError):
    """Carry one or more user-correctable packet errors."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else errors
        super().__init__(self.errors[0] if self.errors else "campaign packet failed")


def canonical_json_bytes(value: Any) -> bytes:
    return strict_json.canonical_bytes(value)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def artifact_ref(path: str, payloads: dict[str, bytes]) -> dict[str, Any]:
    data = payloads[path]
    return {"path": path, "sha256": sha256_bytes(data), "size_bytes": len(data)}


def safe_relative_path(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def prefix_collision(paths: set[str]) -> tuple[str, str] | None:
    ordered = sorted(paths)
    for index, left in enumerate(ordered):
        left_parts = PurePosixPath(left).parts
        for right in ordered[index + 1 :]:
            right_parts = PurePosixPath(right).parts
            if len(left_parts) < len(right_parts) and right_parts[: len(left_parts)] == left_parts:
                return left, right
    return None


def validate_payload_budget(payloads: dict[str, bytes]) -> None:
    if len(payloads) > MAX_PACKET_FILES:
        raise PacketError(f"packet exceeds the {MAX_PACKET_FILES}-file limit")
    total = sum(len(data) for data in payloads.values())
    if total > MAX_PACKET_BYTES:
        raise PacketError(f"packet exceeds the {MAX_PACKET_BYTES}-byte aggregate limit")


def read_regular(path: Path, context: str, *, maximum_bytes: int) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise PacketError(f"{context}: cannot inspect file: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise PacketError(f"{context}: file must not be a symlink")
    if not stat.S_ISREG(mode):
        raise PacketError(f"{context}: path must be a regular file")
    size = path.stat().st_size
    if size > maximum_bytes:
        raise PacketError(f"{context}: file exceeds the {maximum_bytes}-byte limit")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise PacketError(f"{context}: opened path is not a regular file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read(maximum_bytes + 1)
    except OSError as exc:
        raise PacketError(f"{context}: cannot read file: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(data) > maximum_bytes:
        raise PacketError(f"{context}: file exceeds the {maximum_bytes}-byte limit")
    return data


def read_relative_regular(
    root: Path,
    relative_path: str,
    context: str,
    *,
    maximum_bytes: int,
) -> bytes:
    if not safe_relative_path(relative_path):
        raise PacketError(f"{context}: path must be a safe relative POSIX path")
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise PacketError(f"{context}: cannot inspect root: {exc}") from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise PacketError(f"{context}: root must be a non-symlink directory")
    current = root
    parts = PurePosixPath(relative_path).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise PacketError(f"{context}: cannot inspect {relative_path}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise PacketError(f"{context}: symlinked paths are forbidden: {relative_path}")
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise PacketError(f"{context}: path component is not a directory: {relative_path}")
        if index == len(parts) - 1 and not stat.S_ISREG(mode):
            raise PacketError(f"{context}: path must be a regular file: {relative_path}")
    return read_regular(current, context, maximum_bytes=maximum_bytes)


def parse_json_object(data: bytes, context: str) -> dict[str, Any]:
    try:
        value = strict_json.loads(data)
    except strict_json.StrictJSONError as exc:
        raise PacketError(f"{context}: file must contain valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PacketError(f"{context}: JSON root must be an object")
    return value


def read_json_object(path: Path, context: str) -> tuple[bytes, dict[str, Any]]:
    data = read_regular(path, context, maximum_bytes=MAX_JSON_BYTES)
    return data, parse_json_object(data, context)


def inferred_artifact_root(lock_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    if lock_path.parent.name == "locks":
        return lock_path.parent.parent
    return lock_path.parent


def target_lock_ref(plan: dict[str, Any]) -> dict[str, Any] | None:
    target = plan.get("target")
    return target.get("target_lock") if isinstance(target, dict) else None


def target_artifact_refs(lock: dict[str, Any]) -> list[dict[str, Any]]:
    values = [lock.get("primary_input"), lock.get("residue_map")]
    return [value for value in values if isinstance(value, dict)]


def compatibility_errors(
    plan: dict[str, Any],
    plan_bytes: bytes,
    target: dict[str, Any],
    target_bytes: bytes,
    qualification: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    campaign_ids = (
        plan.get("campaign_id"),
        target.get("campaign_id"),
        qualification.get("campaign_id"),
    )
    if not (campaign_ids[0] == campaign_ids[1] == campaign_ids[2]):
        errors.append("plan, target lock, and qualification ledger must use one campaign_id")

    reference = target_lock_ref(plan)
    if not isinstance(reference, dict):
        errors.append("plan.target.target_lock must be an artifact reference")
    else:
        if set(reference) != {"path", "sha256", "size_bytes"}:
            errors.append("plan.target.target_lock must contain path, sha256, and size_bytes")
        if not safe_relative_path(reference.get("path")):
            errors.append("plan.target.target_lock.path must be a safe relative POSIX path")
        if reference.get("sha256") != sha256_bytes(target_bytes):
            errors.append("plan.target.target_lock SHA-256 does not match the supplied lock")
        if reference.get("size_bytes") != len(target_bytes):
            errors.append("plan.target.target_lock byte count does not match the supplied lock")

    plan_target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
    if plan_target.get("identifier") != target.get("target_id"):
        errors.append("plan target identifier must match target lock target_id")
    if plan_target.get("confidentiality") != target.get("confidentiality"):
        errors.append("plan target confidentiality must match the target lock")
    if plan_target.get("source_lock") != target.get("source_lock"):
        errors.append("plan target source_lock must exactly match the target lock")

    locked_primary_input = target.get("primary_input")
    if not isinstance(locked_primary_input, dict) or (
        plan_target.get("structure_or_sequence") != locked_primary_input.get("path")
    ):
        errors.append("plan primary target path must match the target lock")

    plan_residue_map = plan_target.get("residue_map")
    locked_residue_map = target.get("residue_map")
    if isinstance(plan_residue_map, dict) and isinstance(locked_residue_map, dict):
        if plan_residue_map.get("artifact") != locked_residue_map.get("path"):
            errors.append("plan residue-map path must match the target lock")
        if plan_residue_map.get("sha256") != locked_residue_map.get("sha256"):
            errors.append("plan residue-map SHA-256 must match the target lock")

    plan_source_chains = plan_target.get("chains")
    locked_chain_rows = target.get("chains")
    locked_source_chains = [
        row.get("source_chain_id")
        for row in locked_chain_rows
        if isinstance(row, dict)
    ] if isinstance(locked_chain_rows, list) else []
    if (
        not isinstance(plan_source_chains, list)
        or len(plan_source_chains) != len(locked_source_chains)
        or set(plan_source_chains) != set(locked_source_chains)
    ):
        errors.append("plan source-chain list must exactly match the target lock")

    plan_chain_rows = plan_target.get("chain_mapping")
    normalized_plan_chains = [
        (row.get("source_chain"), row.get("campaign_chain"), row.get("role"))
        for row in plan_chain_rows
        if isinstance(row, dict)
    ] if isinstance(plan_chain_rows, list) else []
    normalized_locked_chains = [
        (row.get("source_chain_id"), row.get("campaign_chain_id"), row.get("role"))
        for row in locked_chain_rows
        if isinstance(row, dict)
    ] if isinstance(locked_chain_rows, list) else []
    if (
        len(normalized_plan_chains) != len(normalized_locked_chains)
        or len(set(normalized_plan_chains)) != len(normalized_plan_chains)
        or set(normalized_plan_chains) != set(normalized_locked_chains)
    ):
        errors.append("plan source, campaign, and role chain mappings must exactly match the target lock")

    plan_site = plan_target.get("site") if isinstance(plan_target.get("site"), dict) else {}
    locked_site = target.get("site") if isinstance(target.get("site"), dict) else {}
    if plan_site.get("mode") != locked_site.get("mode"):
        errors.append("plan site mode must match the target lock")
    if plan_site.get("numbering_scheme") != locked_site.get("numbering_scheme"):
        errors.append("plan site numbering scheme must match the target lock")
    if plan_site.get("evidence") != locked_site.get("evidence"):
        errors.append("plan site evidence must match the target lock")
    locked_residues = [
        f"{row.get('campaign_chain_id')}:{row.get('campaign_residue_number')}"
        for row in locked_site.get("residues", [])
        if isinstance(row, dict)
    ]
    declared_residues = plan_site.get("residues")
    if (
        not isinstance(declared_residues, list)
        or len(declared_residues) != len(locked_residues)
        or len(set(declared_residues)) != len(declared_residues)
        or set(declared_residues) != set(locked_residues)
    ):
        errors.append("plan site residues must match target-lock campaign numbering")

    plan_stages = plan.get("execution", {}).get("stages", [])
    qualification_stages = qualification.get("stages", [])
    plan_ids = [plan_stage_id(stage) for stage in plan_stages if isinstance(stage, dict)]
    qualification_ids = [
        stage.get("stage_id") for stage in qualification_stages if isinstance(stage, dict)
    ]
    if (
        len(set(plan_ids)) != len(plan_ids)
        or len(set(qualification_ids)) != len(qualification_ids)
        or plan_ids != qualification_ids
    ):
        errors.append(
            "resolved plan stage IDs must match qualification stage IDs once each and in declared order"
        )
    qualification_by_id = {
        stage.get("stage_id"): stage for stage in qualification_stages if isinstance(stage, dict)
    }
    for stage in plan_stages:
        if not isinstance(stage, dict):
            continue
        stage_id = plan_stage_id(stage)
        qualified = qualification_by_id.get(stage_id)
        if not isinstance(qualified, dict):
            continue
        capability = qualified.get("capability")
        if not isinstance(capability, dict) or capability.get("id") != stage.get("capability"):
            errors.append(f"stage {stage_id}: capability must match the qualification ledger")
        state = qualified.get("evidence_state")
        if QUALIFICATION_RANK.get(state, -1) >= QUALIFICATION_RANK["bound"]:
            if stage.get("route_kind") != qualified.get("route_kind"):
                errors.append(f"stage {stage_id}: route_kind must match the bound qualification")
            if stage.get("provider") != qualified.get("provider"):
                errors.append(f"stage {stage_id}: provider must match the bound qualification")
            price = qualified.get("price")
            if isinstance(price, dict) and price.get("estimate_usd") is not None:
                if float(stage.get("estimated_cost_usd", -1)) != float(price["estimate_usd"]):
                    errors.append(f"stage {stage_id}: estimated cost must match the qualification ledger")

    if not plan_bytes:
        errors.append("plan bytes must not be empty")
    return errors


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def plan_stage_id(stage: dict[str, Any]) -> Any:
    """Return explicit stage identity, with role as the v1 compatibility default."""
    value = stage.get("stage_id")
    return value if isinstance(value, str) and value else stage.get("role")


def overall_claim_ceiling(
    plan: dict[str, Any], target: dict[str, Any], qualification: dict[str, Any]
) -> str:
    values = [
        plan.get("evidence", {}).get("claim_ceiling"),
        target.get("claim_ceiling"),
        qualification.get("claim_ceiling"),
    ]
    valid = [value for value in values if value in CLAIM_RANK]
    return min(valid, key=CLAIM_RANK.get) if valid else "plan-only"


def packet_id_for(
    plan_bytes: bytes,
    target_path: str,
    target_bytes: bytes,
    qualification_bytes: bytes,
    target_artifacts: dict[str, bytes],
) -> str:
    inputs = {
        PLAN_PATH: plan_bytes,
        target_path: target_bytes,
        QUALIFICATION_PATH: qualification_bytes,
        **target_artifacts,
    }
    identity = {
        "schema_version": PACKET_ID_SCHEMA,
        "inputs": [artifact_ref(path, inputs) for path in sorted(inputs)],
    }
    return sha256_bytes(canonical_json_bytes(identity))


def build_graph_and_status(
    plan: dict[str, Any],
    target: dict[str, Any],
    qualification: dict[str, Any],
    plan_warnings: list[str],
    packet_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign_id = plan["campaign_id"]
    plan_stages = plan.get("execution", {}).get("stages", [])
    qualification_by_id = {
        stage["stage_id"]: stage
        for stage in qualification.get("stages", [])
        if isinstance(stage, dict) and isinstance(stage.get("stage_id"), str)
    }
    blockers: list[str] = []
    if plan.get("mode") != "execute":
        blockers.append("plan mode must be execute")
    if qualification.get("mode") != "execute":
        blockers.append("qualification mode must be execute")
    if target.get("claim_ceiling") != "transport-proven":
        blockers.append("target/site lock must reach the transport-proven claim ceiling")
    if plan_warnings:
        blockers.extend(f"plan warning: {warning}" for warning in plan_warnings)
    declared_blockers = plan.get("blockers")
    if isinstance(declared_blockers, list):
        blockers.extend(f"plan blocker: {value}" for value in declared_blockers)
    if qualification.get("unpriced_work"):
        blockers.append("qualification ledger retains unpriced work")
    graph_stages: list[dict[str, Any]] = []
    previous: str | None = None
    for index, stage in enumerate(plan_stages):
        role = stage.get("role") if isinstance(stage, dict) else None
        stage_id = plan_stage_id(stage) if isinstance(stage, dict) else None
        qualified = qualification_by_id.get(stage_id, {})
        stage_blockers: list[str] = []
        state = qualified.get("evidence_state")
        if QUALIFICATION_RANK.get(state, -1) < QUALIFICATION_RANK["scientifically-qualified"]:
            stage_blockers.append(
                f"qualification evidence must reach scientifically-qualified; found {state}"
            )
        if qualified.get("route_kind") == "unbound" or qualified.get("provider") is None:
            stage_blockers.append("route and provider remain unbound")
        price = qualified.get("price") if isinstance(qualified.get("price"), dict) else {}
        if price.get("estimate_usd") is None or price.get("confidence") == "unknown":
            stage_blockers.append("price remains unqualified")
        blockers.extend(f"stage {stage_id}: {value}" for value in stage_blockers)
        graph_stages.append(
            {
                "declared_index": index,
                "stage_id": stage_id,
                "role": role,
                "previous_stage_id": previous,
                "capability": stage.get("capability") if isinstance(stage, dict) else None,
                "route_kind": stage.get("route_kind") if isinstance(stage, dict) else None,
                "provider": stage.get("provider") if isinstance(stage, dict) else None,
                "estimated_cost_usd": (
                    stage.get("estimated_cost_usd") if isinstance(stage, dict) else None
                ),
                "qualification_state": state,
                "blockers": stage_blockers,
            }
        )
        previous = stage_id

    contract_blockers = unique(blockers)
    qualification_declarations_complete = not contract_blockers
    blockers = [*contract_blockers, EVIDENCE_LINKAGE_BLOCKER]
    eligible = False
    estimate = plan.get("budget", {}).get("estimate_usd")
    graph = {
        "schema_version": GRAPH_SCHEMA,
        "campaign_id": campaign_id,
        "packet_id": packet_id,
        "ordering_semantics": (
            "Stages retain execution.stages list order; this packet does not infer extra dependencies."
        ),
        "stages": graph_stages,
    }
    status = {
        "schema_version": STATUS_SCHEMA,
        "campaign_id": campaign_id,
        "packet_id": packet_id,
        "packet_state": "materialized-blocked",
        "dispatch_eligible": eligible,
        "dispatch_attempted": False,
        "next_stage_id": None,
        "claim_ceiling": MATERIALIZER_CLAIM_CEILING,
        "declared_source_claim_ceiling": overall_claim_ceiling(
            plan, target, qualification
        ),
        "qualification_declarations_complete": qualification_declarations_complete,
        "stage_count": len(graph_stages),
        "estimated_cost_usd": estimate,
        "maximum_spend_usd": plan.get("budget", {}).get("maximum_spend_usd"),
        "blockers": blockers,
        "plan_warnings": plan_warnings,
        "immutable_base_packet": True,
        "runtime_updates_require_overlay_receipts": True,
    }
    return graph, status


def render_report(status: dict[str, Any]) -> bytes:
    dispatch = "eligible; no dispatch attempted" if status["dispatch_eligible"] else "blocked"
    blockers = status["blockers"]
    blocker_lines = (
        "\n".join(f"{index}. {value}" for index, value in enumerate(blockers, start=1))
        if blockers
        else "None."
    )
    next_action = (
        "A future evidence-linked executor may consume a new compatible packet. This command never dispatches work."
        if status["dispatch_eligible"]
        else "Resolve the listed blockers, update the source contracts, and materialize a new packet."
    )
    text = (
        "# Campaign packet report\n\n"
        f"Outcome: the local campaign packet is materialized and hash-bound. Dispatch is {dispatch}.\n\n"
        "## Decision record\n\n"
        f"- Campaign: `{status['campaign_id']}`\n"
        f"- Claim ceiling: `{status['claim_ceiling']}`\n"
        f"- Declared source ceiling: `{status['declared_source_claim_ceiling']}`\n"
        f"- Qualification declarations complete: {str(status['qualification_declarations_complete']).lower()}\n"
        f"- Stages: {status['stage_count']}\n"
        f"- Estimated cost: {status['estimated_cost_usd']} USD\n"
        f"- Maximum spend: {status['maximum_spend_usd']} USD\n"
        "- Remote jobs started: 0\n"
        "- Runtime updates: separate, manifest-bound overlay receipts\n\n"
        "## Blockers\n\n"
        f"{blocker_lines}\n\n"
        "## Next action\n\n"
        f"{next_action}\n"
    )
    return text.encode("utf-8")


def build_payloads(
    plan_bytes: bytes,
    plan: dict[str, Any],
    target_bytes: bytes,
    target: dict[str, Any],
    qualification_bytes: bytes,
    qualification: dict[str, Any],
    target_artifacts: dict[str, bytes],
    plan_warnings: list[str],
    packet_id: str,
) -> dict[str, bytes]:
    reference = target_lock_ref(plan)
    if not isinstance(reference, dict) or not safe_relative_path(reference.get("path")):
        raise PacketError("plan.target.target_lock must contain a safe artifact path")
    target_path = reference["path"]
    reserved = {
        PLAN_PATH,
        QUALIFICATION_PATH,
        GRAPH_PATH,
        STATUS_PATH,
        REPORT_PATH,
        RECEIPT_PATH,
        MANIFEST_PATH,
        MANIFEST_SHA_PATH,
    }
    input_paths = {target_path, *target_artifacts}
    collisions = sorted(reserved & input_paths)
    if collisions:
        raise PacketError(f"input artifact paths collide with packet metadata: {', '.join(collisions)}")
    if len(input_paths) != 1 + len(target_artifacts):
        raise PacketError("target lock and target artifacts must use distinct paths")
    collision = prefix_collision(reserved | input_paths)
    if collision is not None:
        raise PacketError(
            f"packet paths collide as file and directory: {collision[0]} and {collision[1]}"
        )

    payloads = {
        PLAN_PATH: plan_bytes,
        target_path: target_bytes,
        QUALIFICATION_PATH: qualification_bytes,
        **target_artifacts,
    }
    graph, status = build_graph_and_status(
        plan, target, qualification, plan_warnings, packet_id
    )
    payloads[GRAPH_PATH] = canonical_json_bytes(graph)
    payloads[STATUS_PATH] = canonical_json_bytes(status)
    payloads[REPORT_PATH] = render_report(status)
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "campaign_id": plan["campaign_id"],
        "packet_id": packet_id,
        "operation": "materialize-local-campaign-packet",
        "network_used": False,
        "dispatch_attempted": False,
        "inputs": [
            artifact_ref(PLAN_PATH, payloads),
            artifact_ref(target_path, payloads),
            artifact_ref(QUALIFICATION_PATH, payloads),
            *[artifact_ref(path, payloads) for path in sorted(target_artifacts)],
        ],
        "outputs": [
            artifact_ref(GRAPH_PATH, payloads),
            artifact_ref(STATUS_PATH, payloads),
            artifact_ref(REPORT_PATH, payloads),
        ],
        "claim_ceiling": MATERIALIZER_CLAIM_CEILING,
        "declared_source_claim_ceiling": status["declared_source_claim_ceiling"],
        "dispatch_eligible": status["dispatch_eligible"],
        "immutable_base_packet": True,
    }
    payloads[RECEIPT_PATH] = canonical_json_bytes(receipt)
    validate_payload_budget(payloads)
    return payloads


def build_manifest(
    payloads: dict[str, bytes], campaign_id: str, packet_id: str
) -> bytes:
    manifest = {
        "schema_version": PACKET_MANIFEST_SCHEMA,
        "campaign_id": campaign_id,
        "packet_id": packet_id,
        "files": [artifact_ref(path, payloads) for path in sorted(payloads)],
    }
    return canonical_json_bytes(manifest)


def validate_output_parent(destination: Path) -> None:
    parent = destination.parent.expanduser().absolute()
    try:
        parent_mode = parent.lstat().st_mode
    except OSError as exc:
        raise PacketError(f"output parent cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
        raise PacketError("output parent must be an existing non-symlink directory")
    for component in (parent, *parent.parents):
        if component == Path(component.anchor) or component in SYSTEM_SYMLINK_ALIASES:
            continue
        try:
            if component.is_symlink():
                raise PacketError(
                    f"output path contains a symlinked ancestor: {component}"
                )
        except OSError as exc:
            raise PacketError(f"output ancestor cannot be inspected: {exc}") from exc


def write_packet(destination: Path, payloads: dict[str, bytes], manifest_bytes: bytes) -> None:
    if destination.exists() or destination.is_symlink():
        raise PacketError("output directory already exists; choose a new packet path")
    validate_output_parent(destination)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        for relative_path, data in sorted(payloads.items()):
            output = temporary / relative_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        manifest = temporary / MANIFEST_PATH
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(manifest_bytes)
        (temporary / MANIFEST_SHA_PATH).write_text(
            f"{sha256_bytes(manifest_bytes)}  packet-manifest.json\n", encoding="ascii"
        )
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def packet_tree_files(packet: Path) -> set[str]:
    def fail_walk(error: OSError) -> None:
        raise PacketError(f"packet tree traversal failed: {error}") from error

    files: set[str] = set()
    for current, directories, names in os.walk(
        packet, followlinks=False, onerror=fail_walk
    ):
        current_path = Path(current)
        for name in [*directories, *names]:
            path = current_path / name
            if path.is_symlink():
                relative = path.relative_to(packet).as_posix()
                raise PacketError(f"packet contains a forbidden symlink: {relative}")
        files.update(
            (current_path / name).relative_to(packet).as_posix() for name in names
        )
    return files


def load_and_validate_inputs(
    plan_path: Path,
    target_path: Path,
    qualification_path: Path,
    artifact_root: Path | None,
) -> tuple[
    bytes,
    dict[str, Any],
    bytes,
    dict[str, Any],
    bytes,
    dict[str, Any],
    list[str],
    Path,
]:
    plan_bytes, plan = read_json_object(plan_path, "plan")
    target_bytes, target = read_json_object(target_path, "target lock")
    qualification_bytes, qualification = read_json_object(
        qualification_path, "qualification ledger"
    )
    target_root = inferred_artifact_root(target_path, artifact_root)
    plan_errors, plan_warnings = validate_plan.validate(plan)
    errors = [f"plan: {value}" for value in plan_errors]
    errors.extend(
        f"target lock: {value}"
        for value in validate_target_site.validate(target, target_root)
    )
    errors.extend(
        f"qualification ledger: {value}"
        for value in validate_qualification.validate(qualification)
    )
    errors.extend(compatibility_errors(plan, plan_bytes, target, target_bytes, qualification))
    if errors:
        raise PacketError(errors)
    return (
        plan_bytes,
        plan,
        target_bytes,
        target,
        qualification_bytes,
        qualification,
        plan_warnings,
        target_root,
    )


def materialize(
    plan_path: Path,
    target_path: Path,
    qualification_path: Path,
    destination: Path,
    artifact_root: Path | None,
) -> dict[str, Any]:
    (
        plan_bytes,
        plan,
        target_bytes,
        target,
        qualification_bytes,
        qualification,
        plan_warnings,
        target_root,
    ) = load_and_validate_inputs(plan_path, target_path, qualification_path, artifact_root)

    artifacts: dict[str, bytes] = {}
    for reference in target_artifact_refs(target):
        relative_path = reference["path"]
        data = read_relative_regular(
            target_root,
            relative_path,
            f"target artifact {relative_path}",
            maximum_bytes=MAX_ARTIFACT_BYTES,
        )
        if len(data) != reference["size_bytes"] or sha256_bytes(data) != reference["sha256"]:
            raise PacketError(f"target artifact {relative_path}: lock hash or byte count changed")
        artifacts[relative_path] = data

    reference = target_lock_ref(plan)
    if not isinstance(reference, dict):
        raise PacketError("plan target lock reference is missing")
    packet_id = packet_id_for(
        plan_bytes,
        reference["path"],
        target_bytes,
        qualification_bytes,
        artifacts,
    )

    payloads = build_payloads(
        plan_bytes,
        plan,
        target_bytes,
        target,
        qualification_bytes,
        qualification,
        artifacts,
        plan_warnings,
        packet_id,
    )
    manifest_bytes = build_manifest(payloads, plan["campaign_id"], packet_id)
    write_packet(destination, payloads, manifest_bytes)
    status = parse_json_object(payloads[STATUS_PATH], "packet status")
    return {
        "ok": True,
        "operation": "materialize",
        "packet": str(destination),
        "file_count": len(payloads) + 2,
        "packet_id": packet_id,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "dispatch_eligible": status["dispatch_eligible"],
        "blockers": status["blockers"],
        "claim_ceiling": status["claim_ceiling"],
    }


def verify_packet(packet: Path) -> dict[str, Any]:
    try:
        mode = packet.lstat().st_mode
    except OSError as exc:
        raise PacketError(f"packet: cannot inspect directory: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise PacketError("packet path must be a non-symlink directory")
    manifest_bytes = read_relative_regular(
        packet, MANIFEST_PATH, "packet manifest", maximum_bytes=MAX_JSON_BYTES
    )
    manifest = parse_json_object(manifest_bytes, "packet manifest")
    sidecar = read_relative_regular(
        packet,
        MANIFEST_SHA_PATH,
        "packet manifest sidecar",
        maximum_bytes=1024,
    )
    expected_sidecar = f"{sha256_bytes(manifest_bytes)}  packet-manifest.json\n".encode(
        "ascii"
    )
    if sidecar != expected_sidecar:
        raise PacketError("packet manifest sidecar does not match the manifest bytes")
    if manifest.get("schema_version") != PACKET_MANIFEST_SCHEMA:
        raise PacketError(f"packet manifest schema must equal {PACKET_MANIFEST_SCHEMA}")
    if set(manifest) != {"schema_version", "campaign_id", "packet_id", "files"}:
        raise PacketError("packet manifest must contain only schema, campaign, packet, and file fields")
    if not isinstance(manifest.get("packet_id"), str) or not SHA256_RE.fullmatch(
        manifest["packet_id"]
    ):
        raise PacketError("packet manifest packet_id must be a lowercase SHA-256")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise PacketError("packet manifest files must be a non-empty array")
    if len(files) > MAX_PACKET_FILES:
        raise PacketError(f"packet manifest exceeds the {MAX_PACKET_FILES}-file limit")
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise PacketError(f"packet manifest files[{index}] must be an object")
        if set(entry) != {"path", "sha256", "size_bytes"}:
            raise PacketError(f"packet manifest files[{index}] has an invalid artifact reference")
        if not isinstance(entry["path"], str):
            raise PacketError(f"packet manifest files[{index}].path must be a string")
    paths = [entry["path"] for entry in files]
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise PacketError("packet manifest paths must be unique and lexically sorted")
    payloads: dict[str, bytes] = {}
    aggregate_size = 0
    for index, entry in enumerate(files):
        relative_path = entry["path"]
        if not safe_relative_path(relative_path):
            raise PacketError(f"packet manifest files[{index}].path is unsafe")
        if not isinstance(entry["sha256"], str) or not SHA256_RE.fullmatch(entry["sha256"]):
            raise PacketError(f"packet manifest files[{index}].sha256 is invalid")
        size_bytes = entry["size_bytes"]
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise PacketError(f"packet manifest files[{index}].size_bytes is invalid")
        if size_bytes > MAX_ARTIFACT_BYTES:
            raise PacketError(f"packet manifest files[{index}] exceeds the per-file limit")
        aggregate_size += size_bytes
        if aggregate_size > MAX_PACKET_BYTES:
            raise PacketError(
                f"packet manifest exceeds the {MAX_PACKET_BYTES}-byte aggregate limit"
            )
        data = read_relative_regular(
            packet,
            relative_path,
            f"packet payload {relative_path}",
            maximum_bytes=MAX_ARTIFACT_BYTES,
        )
        if len(data) != entry["size_bytes"] or sha256_bytes(data) != entry["sha256"]:
            raise PacketError(f"packet payload {relative_path}: manifest hash or byte count mismatch")
        payloads[relative_path] = data

    actual_files = packet_tree_files(packet)
    expected_files = set(paths) | {MANIFEST_PATH, MANIFEST_SHA_PATH}
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if extra:
            details.append(f"undeclared: {', '.join(extra)}")
        raise PacketError(f"packet file set differs from the manifest ({'; '.join(details)})")

    plan = parse_json_object(payloads.get(PLAN_PATH, b""), "packet plan")
    reference = target_lock_ref(plan)
    target_path = reference.get("path") if isinstance(reference, dict) else None
    if not safe_relative_path(target_path) or target_path not in payloads:
        raise PacketError("packet plan target lock path is missing from the manifest")
    target = parse_json_object(payloads[target_path], "packet target lock")
    qualification = parse_json_object(
        payloads.get(QUALIFICATION_PATH, b""), "packet qualification ledger"
    )
    plan_errors, plan_warnings = validate_plan.validate(plan)
    errors = [f"packet plan: {value}" for value in plan_errors]
    errors.extend(
        f"packet target lock: {value}"
        for value in validate_target_site.validate(target, packet)
    )
    errors.extend(
        f"packet qualification ledger: {value}"
        for value in validate_qualification.validate(qualification)
    )
    errors.extend(
        compatibility_errors(plan, payloads[PLAN_PATH], target, payloads[target_path], qualification)
    )
    if errors:
        raise PacketError(errors)

    target_artifacts = {
        reference["path"]: payloads[reference["path"]]
        for reference in target_artifact_refs(target)
    }
    packet_id = packet_id_for(
        payloads[PLAN_PATH],
        target_path,
        payloads[target_path],
        payloads[QUALIFICATION_PATH],
        target_artifacts,
    )
    if manifest.get("campaign_id") != plan.get("campaign_id"):
        raise PacketError("packet manifest campaign_id differs from the sealed plan")
    if manifest.get("packet_id") != packet_id:
        raise PacketError("packet manifest packet_id differs from the sealed inputs")
    expected_payloads = build_payloads(
        payloads[PLAN_PATH],
        plan,
        payloads[target_path],
        target,
        payloads[QUALIFICATION_PATH],
        qualification,
        target_artifacts,
        plan_warnings,
        packet_id,
    )
    if set(expected_payloads) != set(payloads):
        raise PacketError("packet payload set does not match the deterministic contract")
    for relative_path, expected in expected_payloads.items():
        if payloads[relative_path] != expected:
            raise PacketError(f"packet payload {relative_path} differs from deterministic output")
    expected_manifest = build_manifest(
        expected_payloads, plan["campaign_id"], packet_id
    )
    if manifest_bytes != expected_manifest:
        raise PacketError("packet manifest differs from deterministic output")

    status = parse_json_object(payloads[STATUS_PATH], "packet status")
    return {
        "ok": True,
        "operation": "status",
        "packet": str(packet),
        "packet_valid": True,
        "packet_id": packet_id,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "dispatch_eligible": status["dispatch_eligible"],
        "dispatch_attempted": False,
        "next_stage_id": status["next_stage_id"],
        "blockers": status["blockers"],
        "claim_ceiling": status["claim_ceiling"],
        "stage_count": status["stage_count"],
    }


def print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    operation = result.get("operation")
    if operation == "materialize":
        print(f"Campaign packet materialized: {result['packet']}")
    elif operation == "resume-check":
        print("Resume check is blocked; no dispatch was attempted.")
    else:
        state = "eligible" if result["dispatch_eligible"] else "blocked"
        print(f"Campaign packet is valid. Dispatch is {state}.")
    for blocker in result.get("blockers", []):
        print(f"BLOCKER: {blocker}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("plan", type=Path)
    materialize_parser.add_argument("target_lock", type=Path)
    materialize_parser.add_argument("qualification", type=Path)
    materialize_parser.add_argument("output", type=Path)
    materialize_parser.add_argument("--artifact-root", type=Path)
    materialize_parser.add_argument("--json", action="store_true")

    for command in ("status", "resume-check"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("packet", type=Path)
        command_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "materialize":
            result = materialize(
                args.plan,
                args.target_lock,
                args.qualification,
                args.output,
                args.artifact_root,
            )
        else:
            result = verify_packet(args.packet)
            result["operation"] = args.command
    except PacketError as exc:
        result = {"ok": False, "operation": args.command, "errors": exc.errors}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for error in exc.errors:
                print(f"ERROR: {error}")
        return 1
    except Exception as exc:  # Keep untrusted input and filesystem failures structured.
        message = f"campaign packet operation failed: {type(exc).__name__}: {exc}"
        result = {"ok": False, "operation": args.command, "errors": [message]}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {message}")
        return 1
    print_result(result, as_json=args.json)
    if args.command == "resume-check":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
