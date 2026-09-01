#!/usr/bin/env python3
"""Normalize one completed BioSymphony hosted-Chai result without executing it.

This adapter is deliberately local.  It reads an already completed
BioSymphony Structure Factory Chai inference receipt plus the matching
``cofold-observations.jsonl`` row, verifies their hashes and copies the four
declared computational artifacts into a new portable artifact tree.  It does
not contact a provider, submit or resume a job, spend money, or mutate the
base campaign packet.
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import campaign_overlay  # noqa: E402
import campaign_packet  # noqa: E402
import validate_qualification  # noqa: E402


NORMALIZER_SCHEMA = "codex-binder-biosymphony-chai-normalizer/v1"
NORMALIZED_RECEIPT_NAME = "companion-stage-receipt.json"
ARTIFACT_PREFIX = "artifacts/biosymphony-chai"
NATIVE_RECEIPT_SCHEMA_VERSION = 1
NATIVE_RUNNER_PROTOCOL = "fal"
MAX_NATIVE_JSON_BYTES = campaign_packet.MAX_JSON_BYTES
MAX_NATIVE_ARTIFACT_BYTES = campaign_packet.MAX_ARTIFACT_BYTES
SHA256_RE = campaign_packet.SHA256_RE

OUTPUT_SPECS = (
    ("predicted_complex_path", "predicted_complex_sha256", "complex.pdb"),
    ("pae_path", "pae_sha256", "pae.json"),
    ("metric_source_path", "metric_source_sha256", "measurement-source.json"),
    ("runner_identity_path", "runner_identity_sha256", "runner-identity.json"),
)


class NormalizationError(ValueError):
    """Carry one or more user-correctable normalization errors."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else errors
        super().__init__(self.errors[0] if self.errors else "receipt normalization failed")


def sha256_bytes(value: bytes) -> str:
    """Return the complete-byte SHA-256 used by the portable contracts."""
    return campaign_packet.sha256_bytes(value)


def require_non_symlink_directory(path: Path, context: str) -> Path:
    """Return one existing directory without accepting a symlink root."""
    root = path.expanduser().absolute()
    try:
        mode = root.lstat().st_mode
    except OSError as exc:
        raise NormalizationError(f"{context}: cannot inspect directory: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise NormalizationError(f"{context}: must be an existing non-symlink directory")
    return root


def native_record_relative(native_root: Path, value: Any, context: str) -> str:
    """Resolve one Structure Factory receipt path into a checked root-relative path.

    Structure Factory native receipts normally carry absolute paths.  The
    normalized receipt must never retain those paths, so this helper accepts
    them only when they are lexically beneath the supplied native root.  The
    later ``read_relative_regular`` call rejects any symlink component before
    bytes are read, including a declared path that would otherwise resolve
    back inside the root.
    """
    if not isinstance(value, str) or not value:
        raise NormalizationError(f"{context}: must be a non-empty path string")
    raw = Path(value).expanduser()
    if raw.is_absolute():
        candidate = raw
    else:
        if not campaign_packet.safe_relative_path(value):
            raise NormalizationError(f"{context}: relative paths must be safe POSIX paths")
        candidate = native_root / value
    try:
        relative = candidate.absolute().relative_to(native_root.absolute()).as_posix()
    except ValueError as exc:
        raise NormalizationError(
            f"{context}: must be beneath --native-root without a path escape"
        ) from exc
    if not campaign_packet.safe_relative_path(relative):
        raise NormalizationError(f"{context}: resolved path is not a safe relative POSIX path")
    return relative


def native_cli_relative(native_root: Path, value: Path, context: str) -> str:
    """Resolve one command-line path into the native-root namespace."""
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return native_record_relative(native_root, str(candidate), context)


def read_native_file(
    native_root: Path,
    relative_path: str,
    context: str,
    *,
    maximum_bytes: int,
) -> bytes:
    """Read one regular native artifact through the packet path guard."""
    try:
        return campaign_packet.read_relative_regular(
            native_root,
            relative_path,
            context,
            maximum_bytes=maximum_bytes,
        )
    except campaign_packet.PacketError as exc:
        raise NormalizationError(exc.errors) from exc


def parse_native_receipt(data: bytes, context: str) -> dict[str, Any]:
    """Parse a native receipt while rejecting ambiguous JSON keys."""
    try:
        return campaign_overlay.parse_strict_json_object(data, context)
    except campaign_overlay.OverlayError as exc:
        raise NormalizationError(exc.errors) from exc


def require_sha256(value: Any, context: str) -> str:
    """Return one lowercase SHA-256 or name the field that needs repair."""
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise NormalizationError(f"{context}: must be a lowercase SHA-256")
    return value


def require_portable_identifier(value: Any, context: str) -> str:
    """Return a portable identifier suitable for a receipt field or path component."""
    if not validate_qualification.portable_identifier(value):
        raise NormalizationError(f"{context}: must be a portable identifier")
    return str(value)


def require_nonnegative_seed(value: int) -> int:
    """Validate the selected Bsf seed before it becomes part of an output path."""
    if value < 0:
        raise NormalizationError("--seed must be a non-negative integer")
    return value


def parse_observations(data: bytes, context: str) -> list[tuple[int, bytes, dict[str, Any]]]:
    """Parse JSONL observations and retain each exact row byte sequence for binding."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NormalizationError(f"{context}: must be UTF-8 JSONL") from exc
    rows: list[tuple[int, bytes, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        raw = line.encode("utf-8")
        rows.append(
            (
                line_number,
                raw,
                parse_native_receipt(raw, f"{context}:{line_number}"),
            )
        )
    if not rows:
        raise NormalizationError(f"{context}: contains no JSON object rows")
    return rows


def select_observation(
    rows: list[tuple[int, bytes, dict[str, Any]]], candidate_id: str, seed: int
) -> tuple[int, bytes, dict[str, Any]]:
    """Select exactly one scored Chai row by its explicit candidate and seed."""
    matches = [
        row
        for row in rows
        if row[2].get("candidate_id") == candidate_id and row[2].get("seed") == seed
    ]
    if len(matches) != 1:
        raise NormalizationError(
            "the observation manifest must contain exactly one row for "
            f"candidate {candidate_id!r} at seed {seed}; found {len(matches)}"
        )
    line_number, raw, row = matches[0]
    required = {
        "status": "scored",
        "predictor": "chai",
        "runner_protocol": NATIVE_RUNNER_PROTOCOL,
    }
    for field, expected in required.items():
        if row.get(field) != expected:
            raise NormalizationError(
                f"observation row {line_number}.{field}: expected {expected!r}"
            )
    return line_number, raw, row


def primary_packet_input(base: dict[str, Any]) -> dict[str, Any]:
    """Return the packet's locked primary input, which must equal the fold input."""
    target = base["plan"].get("target")
    path = target.get("structure_or_sequence") if isinstance(target, dict) else None
    if not campaign_packet.safe_relative_path(path):
        raise NormalizationError(
            "the frozen plan must expose a safe target.structure_or_sequence path"
        )
    reference = base["manifest_by_path"].get(path)
    if not isinstance(reference, dict):
        raise NormalizationError(
            "the frozen primary input is absent from the verified packet manifest"
        )
    return reference


def frozen_stage(base: dict[str, Any], stage_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return one exact FAL stage from both frozen plan and qualification records."""
    plan_stage, qualified_stage = campaign_overlay.stage_by_id(base, stage_id)
    if plan_stage is None or qualified_stage is None:
        raise NormalizationError(
            "--stage-id must identify exactly one frozen plan and qualification stage"
        )
    if plan_stage.get("route_kind") != "fal" or qualified_stage.get("route_kind") != "fal":
        raise NormalizationError(
            "the selected stage must be a BioSymphony hosted-Chai FAL route in both records"
        )
    capability = qualified_stage.get("capability")
    if not isinstance(capability, dict):
        raise NormalizationError("the qualified stage must expose a capability identity")
    for field in ("id", "revision"):
        require_portable_identifier(capability.get(field), f"qualified stage capability.{field}")
    require_portable_identifier(plan_stage.get("provider"), "frozen plan stage provider")
    if plan_stage.get("provider") != qualified_stage.get("provider"):
        raise NormalizationError("the frozen plan and qualification providers must match")
    return plan_stage, qualified_stage


def verify_native_receipt(
    native_root: Path,
    receipt_relative: str,
    native_receipt_bytes: bytes,
) -> tuple[dict[str, Any], str]:
    """Verify the native receipt and its raw Structure Factory inference artifacts."""
    receipt = parse_native_receipt(native_receipt_bytes, "native inference receipt")
    if receipt.get("schema_version") != NATIVE_RECEIPT_SCHEMA_VERSION:
        raise NormalizationError(
            "native inference receipt.schema_version must equal "
            f"{NATIVE_RECEIPT_SCHEMA_VERSION}"
        )
    if receipt.get("ok") is not True:
        raise NormalizationError("native inference receipt must record ok: true")
    if receipt.get("runner_protocol") != NATIVE_RUNNER_PROTOCOL:
        raise NormalizationError("native inference receipt must record runner_protocol: fal")
    require_portable_identifier(
        receipt.get("fal_request_id"), "native inference receipt.fal_request_id"
    )
    input_sha256 = require_sha256(
        receipt.get("input_fasta_sha256"), "native inference receipt.input_fasta_sha256"
    )
    raw_structure_relative = native_record_relative(
        native_root, receipt.get("structure_path"), "native inference receipt.structure_path"
    )
    raw_structure = read_native_file(
        native_root,
        raw_structure_relative,
        "native inference structure",
        maximum_bytes=MAX_NATIVE_ARTIFACT_BYTES,
    )
    if sha256_bytes(raw_structure) != require_sha256(
        receipt.get("structure_sha256"), "native inference receipt.structure_sha256"
    ):
        raise NormalizationError("native inference structure differs from its recorded SHA-256")
    raw_pae_relative = native_record_relative(
        native_root, receipt.get("pae_record"), "native inference receipt.pae_record"
    )
    read_native_file(
        native_root,
        raw_pae_relative,
        "native inference PAE record",
        maximum_bytes=MAX_NATIVE_ARTIFACT_BYTES,
    )
    if receipt_relative == raw_structure_relative or receipt_relative == raw_pae_relative:
        raise NormalizationError("native receipt path must not alias a declared inference artifact")
    return receipt, input_sha256


def verified_output_payloads(
    native_root: Path,
    observation: dict[str, Any],
    *,
    output_prefix: str,
) -> dict[str, bytes]:
    """Read and hash-check the normalized Bsf output set before staging it."""
    payloads: dict[str, bytes] = {}
    for path_field, hash_field, name in OUTPUT_SPECS:
        relative = native_record_relative(
            native_root, observation.get(path_field), f"observation.{path_field}"
        )
        data = read_native_file(
            native_root,
            relative,
            f"observation artifact {path_field}",
            maximum_bytes=MAX_NATIVE_ARTIFACT_BYTES,
        )
        expected = require_sha256(observation.get(hash_field), f"observation.{hash_field}")
        if sha256_bytes(data) != expected:
            raise NormalizationError(
                f"observation artifact {path_field} differs from its recorded SHA-256"
            )
        normalized_path = PurePosixPath(output_prefix, name).as_posix()
        payloads[normalized_path] = data
    return payloads


def normalized_receipt_id(native_receipt_bytes: bytes, observation_row: bytes) -> str:
    """Derive a portable ID from the exact native receipt and selected JSONL row."""
    identity = {
        "schema_version": NORMALIZER_SCHEMA,
        "native_inference_receipt_sha256": sha256_bytes(native_receipt_bytes),
        "native_observation_row_sha256": sha256_bytes(observation_row),
    }
    return "biosymphony-chai-" + sha256_bytes(campaign_packet.canonical_json_bytes(identity))


def build_normalized_receipt(
    base: dict[str, Any],
    plan_stage: dict[str, Any],
    qualified_stage: dict[str, Any],
    *,
    receipt_id: str,
    provider_request_id: str,
    inputs: list[dict[str, Any]],
    output_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Build the strict portable receipt exclusively from frozen and hashed facts."""
    outputs = [
        campaign_packet.artifact_ref(path, output_payloads)
        for path in sorted(output_payloads)
    ]
    return {
        "schema_version": campaign_overlay.RECEIPT_SCHEMA,
        "receipt_id": receipt_id,
        "campaign_id": base["campaign_id"],
        "base_packet_id": base["packet_id"],
        "base_manifest_sha256": base["manifest_sha256"],
        "stage_id": campaign_packet.plan_stage_id(plan_stage),
        "capability": qualified_stage["capability"],
        "route_kind": plan_stage["route_kind"],
        "provider": plan_stage["provider"],
        "execution_state": "completed",
        "provider_request_id": provider_request_id,
        "inputs": inputs,
        "outputs": outputs,
        "cost": {"status": "unknown", "estimate_usd": None, "observed_usd": None},
        # The native hosted-Chai receipt contains no cleanup proof and names no
        # campaign-owned runner or resource. Do not fabricate provider-internal
        # lifecycle evidence.
        "cleanup_state": "not-applicable",
        "claim_ceiling": "transport-proven",
    }


def write_normalized_stage(
    destination: Path, receipt: dict[str, Any], output_payloads: dict[str, bytes]
) -> None:
    """Atomically write a new receipt/artifact tree without overwriting anything."""
    if destination.exists() or destination.is_symlink():
        raise NormalizationError("output directory already exists; choose a new normalization path")
    try:
        campaign_packet.validate_output_parent(destination)
    except campaign_packet.PacketError as exc:
        raise NormalizationError(exc.errors) from exc
    receipt_bytes = campaign_packet.canonical_json_bytes(receipt)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        for relative_path, data in sorted(output_payloads.items()):
            output = temporary / relative_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        (temporary / NORMALIZED_RECEIPT_NAME).write_bytes(receipt_bytes)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def normalize_stage(
    base_packet: Path,
    native_root_path: Path,
    native_receipt_path: Path,
    observations_path: Path,
    destination: Path,
    *,
    stage_id: str,
    candidate_id: str,
    seed: int,
) -> dict[str, Any]:
    """Normalize one completed Bsf hosted-Chai prediction into an overlay receipt."""
    native_root = require_non_symlink_directory(native_root_path, "--native-root")
    base = campaign_overlay.load_base_packet(base_packet)
    stage_id = require_portable_identifier(stage_id, "--stage-id")
    candidate_id = require_portable_identifier(candidate_id, "--candidate-id")
    seed = require_nonnegative_seed(seed)
    plan_stage, qualified_stage = frozen_stage(base, stage_id)

    receipt_relative = native_cli_relative(
        native_root, native_receipt_path, "native inference receipt"
    )
    native_receipt_bytes = read_native_file(
        native_root,
        receipt_relative,
        "native inference receipt",
        maximum_bytes=MAX_NATIVE_JSON_BYTES,
    )
    native_receipt, input_sha256 = verify_native_receipt(
        native_root, receipt_relative, native_receipt_bytes
    )

    observations_relative = native_cli_relative(
        native_root, observations_path, "native observation manifest"
    )
    observation_bytes = read_native_file(
        native_root,
        observations_relative,
        "native observation manifest",
        maximum_bytes=MAX_NATIVE_JSON_BYTES,
    )
    line_number, raw_observation, observation = select_observation(
        parse_observations(observation_bytes, "native observation manifest"), candidate_id, seed
    )
    if observation.get("fal_request_id") != native_receipt.get("fal_request_id"):
        raise NormalizationError(
            f"observation row {line_number}.fal_request_id does not match the native receipt"
        )
    if require_sha256(
        observation.get("inference_receipt_sha256"),
        f"observation row {line_number}.inference_receipt_sha256",
    ) != sha256_bytes(native_receipt_bytes):
        raise NormalizationError(
            f"observation row {line_number} does not hash-bind the native inference receipt"
        )
    observation_receipt_relative = native_record_relative(
        native_root,
        observation.get("inference_receipt_path"),
        f"observation row {line_number}.inference_receipt_path",
    )
    if observation_receipt_relative != receipt_relative:
        raise NormalizationError(
            f"observation row {line_number} points at a different native inference receipt"
        )
    if require_sha256(
        observation.get("fold_input_fasta_sha256"),
        f"observation row {line_number}.fold_input_fasta_sha256",
    ) != input_sha256:
        raise NormalizationError(
            f"observation row {line_number} does not match the native fold-input SHA-256"
        )

    locked_input = primary_packet_input(base)
    if locked_input["sha256"] != input_sha256:
        raise NormalizationError(
            "the native fold input does not match the frozen packet primary input; "
            "materialize the packet before the Chai call with the exact submitted fold-input FASTA"
        )
    output_prefix = PurePosixPath(
        ARTIFACT_PREFIX, candidate_id, f"seed-{seed:04d}"
    ).as_posix()
    output_payloads = verified_output_payloads(
        native_root, observation, output_prefix=output_prefix
    )
    receipt = build_normalized_receipt(
        base,
        plan_stage,
        qualified_stage,
        receipt_id=normalized_receipt_id(native_receipt_bytes, raw_observation),
        provider_request_id=str(native_receipt["fal_request_id"]),
        inputs=[locked_input],
        output_payloads=output_payloads,
    )
    try:
        campaign_overlay.validate_receipt(receipt, base)
    except campaign_overlay.OverlayError as exc:
        raise NormalizationError(exc.errors) from exc
    write_normalized_stage(destination, receipt, output_payloads)
    return {
        "ok": True,
        "operation": "normalize-biosymphony-chai-stage",
        "receipt": str(destination / NORMALIZED_RECEIPT_NAME),
        "receipt_id": receipt["receipt_id"],
        "stage_id": stage_id,
        "artifact_count": len(output_payloads),
        "network_used": False,
        "dispatch_attempted": False,
        "provider_execution_verified": False,
    }


def print_result(result: dict[str, Any], *, as_json: bool) -> None:
    """Emit a compact machine- or human-readable local-operation record."""
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    print(f"Normalized BioSymphony Chai receipt: {result['receipt']}")
    print("No provider call, dispatch, spend, or base-packet mutation was performed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize_parser = subparsers.add_parser("normalize-stage")
    normalize_parser.add_argument("base_packet", type=Path)
    normalize_parser.add_argument("native_root", type=Path)
    normalize_parser.add_argument("native_receipt", type=Path)
    normalize_parser.add_argument("observations", type=Path)
    normalize_parser.add_argument("output", type=Path)
    normalize_parser.add_argument("--stage-id", required=True)
    normalize_parser.add_argument("--candidate-id", required=True)
    normalize_parser.add_argument("--seed", type=int, required=True)
    normalize_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = normalize_stage(
            args.base_packet,
            args.native_root,
            args.native_receipt,
            args.observations,
            args.output,
            stage_id=args.stage_id,
            candidate_id=args.candidate_id,
            seed=args.seed,
        )
    except (NormalizationError, campaign_overlay.OverlayError, campaign_packet.PacketError) as exc:
        result = {"ok": False, "operation": args.command, "errors": exc.errors}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for error in exc.errors:
                print(f"ERROR: {error}")
        return 1
    except Exception as exc:  # Keep untrusted input and filesystem failures structured.
        result = {
            "ok": False,
            "operation": args.command,
            "errors": [f"receipt normalization failed: {type(exc).__name__}: {exc}"],
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {result['errors'][0]}")
        return 1
    print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
