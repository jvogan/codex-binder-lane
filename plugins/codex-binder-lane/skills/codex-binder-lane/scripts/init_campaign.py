#!/usr/bin/env python3
"""Initialize a conservative, provider-free Binder Lane campaign workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
PLAN_TEMPLATE = ASSET_DIR / "codex-binder-plan.template.json"
TARGET_LOCK_TEMPLATE = ASSET_DIR / "target-site-lock.template.json"
RESIDUE_MAP_TEMPLATE = ASSET_DIR / "residue-map.template.csv"
PROFILE_PATHS = {
    "classic": ASSET_DIR
    / "profiles"
    / "classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json",
    "complexa": ASSET_DIR
    / "profiles"
    / "complexa-codesign-independent-holo-apo-validation.plan.json",
}
OUTPUT_NAMES = {
    "plan": "codex-binder-plan.json",
    "qualification": "qualification-ledger.json",
    "target_lock": "target-site-lock.template.json",
    "residue_map": "residue-map.template.csv",
}
CAMPAIGN_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_CAMPAIGN_ID_LENGTH = 128
SYSTEM_SYMLINK_ALIASES = {Path("/").joinpath(name) for name in ("etc", "tmp", "var")}
SUMMARY_SCHEMA = "codex-binder-campaign-initialization/v1"


class InitializationError(ValueError):
    """Carry one or more user-correctable initialization errors."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else errors
        super().__init__(
            self.errors[0] if self.errors else "campaign initialization failed"
        )


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_campaign_id(campaign_id: str) -> None:
    if (
        len(campaign_id) > MAX_CAMPAIGN_ID_LENGTH
        or CAMPAIGN_ID_RE.fullmatch(campaign_id) is None
    ):
        raise InitializationError(
            "campaign_id must be a lowercase portable slug of at most 128 characters "
            "using letters, digits, and single hyphens"
        )


def read_json_asset(path: Path, label: str) -> dict[str, Any]:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise InitializationError(f"{label} cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise InitializationError(f"{label} must be a regular non-symlink file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InitializationError(f"{label} cannot be read as JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise InitializationError(f"{label} must contain a JSON object")
    return value


def read_bytes_asset(path: Path, label: str) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise InitializationError(f"{label} cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise InitializationError(f"{label} must be a regular non-symlink file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InitializationError(f"{label} cannot be read: {exc}") from exc


def validate_output_destination(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise InitializationError("output directory already exists; choose a new path")
    parent = destination.parent
    try:
        parent_mode = parent.lstat().st_mode
    except OSError as exc:
        raise InitializationError(f"output parent cannot be inspected: {exc}") from exc
    if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
        raise InitializationError(
            "output parent must be an existing non-symlink directory"
        )
    for component in (parent, *parent.parents):
        if component == Path(component.anchor) or component in SYSTEM_SYMLINK_ALIASES:
            continue
        try:
            if component.is_symlink():
                raise InitializationError(
                    f"output path contains a symlinked ancestor: {component}"
                )
        except OSError as exc:
            raise InitializationError(
                f"output ancestor cannot be inspected: {exc}"
            ) from exc


def build_payloads(
    campaign_id: str, profile: str, confidentiality: str
) -> dict[str, bytes]:
    plan = read_json_asset(PLAN_TEMPLATE, "campaign plan template")
    qualification = read_json_asset(
        PROFILE_PATHS[profile], f"{profile} qualification profile"
    )
    target_lock = read_json_asset(TARGET_LOCK_TEMPLATE, "target/site lock template")
    residue_map = read_bytes_asset(RESIDUE_MAP_TEMPLATE, "residue-map template")

    plan["campaign_id"] = campaign_id
    plan["mode"] = "plan"
    plan["target"]["confidentiality"] = confidentiality
    plan["target"]["target_lock"]["path"] = OUTPUT_NAMES["target_lock"]
    plan["target"]["residue_map"]["artifact"] = OUTPUT_NAMES["residue_map"]
    plan["authorization"] = {
        "paid_compute_authorized": False,
        "private_data_authorized": False,
        "restricted_license_authorized": False,
    }
    plan["evidence"]["claim_ceiling"] = "plan-only"

    qualification["campaign_id"] = campaign_id
    qualification["claim_ceiling"] = "plan-only"
    qualification["data_classification"] = confidentiality
    qualification["mode"] = "plan"
    qualification["private_data_authorized"] = False

    target_lock["campaign_id"] = campaign_id
    target_lock["claim_ceiling"] = "plan-only"
    target_lock["confidentiality"] = confidentiality
    target_lock["residue_map"]["path"] = OUTPUT_NAMES["residue_map"]

    return {
        OUTPUT_NAMES["plan"]: canonical_json_bytes(plan),
        OUTPUT_NAMES["qualification"]: canonical_json_bytes(qualification),
        OUTPUT_NAMES["target_lock"]: canonical_json_bytes(target_lock),
        OUTPUT_NAMES["residue_map"]: residue_map,
    }


def write_new_directory(destination: Path, payloads: dict[str, bytes]) -> None:
    validate_output_destination(destination)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent)
    )
    try:
        for relative_path, data in sorted(payloads.items()):
            (temporary / relative_path).write_bytes(data)
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def initialize(
    campaign_id: str, output: Path, *, profile: str, confidentiality: str
) -> dict[str, Any]:
    validate_campaign_id(campaign_id)
    destination = output.expanduser().absolute()
    payloads = build_payloads(campaign_id, profile, confidentiality)
    write_new_directory(destination, payloads)
    files = [
        {
            "path": path,
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
        }
        for path, data in sorted(payloads.items())
    ]
    return {
        "schema_version": SUMMARY_SCHEMA,
        "ok": True,
        "status": "initialized-plan-only",
        "campaign_id": campaign_id,
        "profile": profile,
        "confidentiality": confidentiality,
        "output": str(destination),
        "files": files,
        "dispatch_eligible": False,
        "network_or_provider_calls": False,
        "next_steps": [
            "Resolve the campaign purpose, target construct, site, scale, controls, and budget in codex-binder-plan.json.",
            "Replace every target/site and residue-map placeholder with reviewed facts and exact artifact hashes.",
            "Qualify identities, revisions, licenses, routes, prices, and evidence before changing the ledger from plan mode.",
            "Run the bundled plan, target/site, and qualification validators before materializing a campaign packet.",
        ],
    }


def print_human_summary(result: dict[str, Any]) -> None:
    print(f"Initialized plan-only Binder Lane campaign: {result['campaign_id']}")
    print(f"Output: {result['output']}")
    print(f"Profile: {result['profile']}")
    print(f"Confidentiality: {result['confidentiality']}")
    print("Files:")
    for item in result["files"]:
        print(f"- {item['path']}")
    print("No network or provider calls were made. Dispatch remains disabled.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_id")
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILE_PATHS), required=True)
    parser.add_argument(
        "--confidentiality",
        choices=("public", "private", "restricted"),
        required=True,
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON summary")
    args = parser.parse_args()

    try:
        result = initialize(
            args.campaign_id,
            args.output,
            profile=args.profile,
            confidentiality=args.confidentiality,
        )
    except InitializationError as exc:
        result = {
            "schema_version": SUMMARY_SCHEMA,
            "ok": False,
            "errors": exc.errors,
            "network_or_provider_calls": False,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            for error in exc.errors:
                print(f"ERROR: {error}")
        return 1
    except Exception as exc:
        result = {
            "schema_version": SUMMARY_SCHEMA,
            "ok": False,
            "errors": [f"campaign initialization failed: {type(exc).__name__}: {exc}"],
            "network_or_provider_calls": False,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {result['errors'][0]}")
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_human_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
