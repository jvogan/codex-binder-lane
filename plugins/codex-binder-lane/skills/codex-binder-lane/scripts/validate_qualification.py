#!/usr/bin/env python3
"""Validate a provider-neutral capability qualification ledger for Binder Lane."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import strict_json  # noqa: E402


SCHEMA_VERSION = "codex-binder-qualification-ledger/v1"
EVIDENCE_STATES = (
    "catalogued",
    "visible",
    "bound",
    "preflight-passed",
    "scientifically-qualified",
    "executed",
    "artifact-validated",
)
ROUTE_KINDS = {
    "unbound",
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
    "manual-handoff",
}
REMOTE_ROUTE_KINDS = ROUTE_KINDS - {"unbound", "local"}
EGRESS_CLASSES = {"unprobed", "local-only", "remote-external"}
CLAIM_CEILINGS = {
    "plan-only",
    "transport-proven",
    "computational-candidate",
    "cross-model-supported",
}
CLAIM_MINIMUM_STATE = {
    "plan-only": "catalogued",
    "transport-proven": "executed",
    "computational-candidate": "artifact-validated",
    "cross-model-supported": "artifact-validated",
}
MODES = {"plan", "dry-run", "execute"}
LICENSE_KINDS = ("code", "weights", "service")
ROOT_KEYS = {
    "campaign_id",
    "claim_ceiling",
    "data_classification",
    "mode",
    "private_data_authorized",
    "schema_version",
    "stages",
    "unpriced_work",
}
STAGE_KEYS = {
    "adapter",
    "artifact_validation",
    "capability",
    "egress_class",
    "evidence_history",
    "evidence_state",
    "input_artifact_types",
    "licenses",
    "model",
    "output_artifact_types",
    "price",
    "provider",
    "route_kind",
    "runtime",
    "source",
    "stage_id",
    "weights",
}
IDENTITY_KEYS = {"id", "revision"}
LICENSE_KEYS = {"commercial_allowed", "license_id", "redistribution_allowed", "source"}
PRICE_KEYS = {"confidence", "estimate_usd", "source"}
PORTABLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
PORTABLE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOURCE_REFERENCE_RE = re.compile(
    r"^(?:catalog|license|pricing|receipt|record):[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)
SECRET_KEY_RE = re.compile(
    r"(?:^|_)(?:access_?token|api_?key|fal_?key|authorization|bearer|client_?secret|"
    r"cookie|credential|password|private_?key|secret|session|token)(?:$|_)"
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
PRIVATE_HOSTNAMES = {
    "localhost",
    "host.docker.internal",
    "metadata.google.internal",
}


def present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def non_negative_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and value >= 0
    )


def check_exact_keys(
    value: Any,
    context: str,
    *,
    allowed: set[str],
    errors: list[str],
) -> dict[str, Any]:
    item = require_object(value, context, errors)
    if not item and not isinstance(value, dict):
        return item
    keys = set(item)
    missing = sorted(allowed - keys)
    extra = sorted(keys - allowed)
    if missing:
        errors.append(f"{context} is missing required keys: {', '.join(missing)}")
    if extra:
        errors.append(f"{context} contains unsupported keys: {', '.join(extra)}")
    return item


def portable_identifier(value: Any, *, slug: bool = False) -> bool:
    expression = PORTABLE_SLUG_RE if slug else PORTABLE_IDENTIFIER_RE
    return isinstance(value, str) and expression.fullmatch(value) is not None


def private_host(value: str) -> str | None:
    candidate = value.strip()
    parsed = urlsplit(candidate) if "://" in candidate else None
    host = parsed.hostname if parsed else candidate
    if not host:
        return None
    normalized = host.strip("[]").lower().rstrip(".")
    if normalized.count(":") == 1 and normalized.rsplit(":", 1)[1].isdigit():
        normalized = normalized.rsplit(":", 1)[0]
    if normalized in PRIVATE_HOSTNAMES or normalized.endswith((".local", ".internal", ".corp", ".lan")):
        return normalized
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return None
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        return normalized
    return None


def secret_findings(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if SECRET_KEY_RE.search(normalized):
                if present(child):
                    findings.append(f"{path}.{key} contains a credential-like value")
            findings.extend(secret_findings(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(secret_findings(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        parsed = urlsplit(value)
        query_keys = {key.lower().replace("-", "_") for key, _ in parse_qsl(parsed.query)}
        if parsed.username or parsed.password or any(SECRET_KEY_RE.search(key) or key in {"key", "sig", "signature"} for key in query_keys):
            findings.append(f"{path} contains a credential-bearing URL")
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            findings.append(f"{path} contains a credential-like string")
        host = private_host(value)
        if host:
            findings.append(f"{path} contains a private host: {host}")
    return findings


def require_object(value: Any, context: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return {}
    return value


def check_identity(value: Any, context: str, *, allow_unknown: bool, errors: list[str]) -> None:
    item = check_exact_keys(value, context, allowed=IDENTITY_KEYS, errors=errors)
    for field in ("id", "revision"):
        if field not in item:
            errors.append(f"{context}.{field} is required")
        elif item[field] is not None and not isinstance(item[field], str):
            errors.append(f"{context}.{field} must be a string or null")
        elif item[field] is not None and not portable_identifier(item[field]):
            errors.append(f"{context}.{field} must be a portable identifier or null")
        elif not allow_unknown and not present(item[field]):
            errors.append(f"{context}.{field} must be bound before preflight")


def check_license(value: Any, context: str, *, require_facts: bool, errors: list[str]) -> None:
    item = check_exact_keys(value, context, allowed=LICENSE_KEYS, errors=errors)
    for field in ("license_id", "source", "commercial_allowed", "redistribution_allowed"):
        if field not in item:
            errors.append(f"{context}.{field} is required")
    for field in ("license_id", "source"):
        current = item.get(field)
        if current is not None and not isinstance(current, str):
            errors.append(f"{context}.{field} must be a string or null")
        elif field == "license_id" and current is not None and not portable_identifier(current):
            errors.append(f"{context}.{field} must be a portable identifier or null")
        if require_facts and not present(current):
            errors.append(f"{context}.{field} is required before preflight")
    source = item.get("source")
    if source is not None and isinstance(source, str) and SOURCE_REFERENCE_RE.fullmatch(source) is None:
        errors.append(f"{context}.source must be a safe source reference or null")
    for field in ("commercial_allowed", "redistribution_allowed"):
        current = item.get(field)
        if current is not None and not isinstance(current, bool):
            errors.append(f"{context}.{field} must be a boolean or null")
        if require_facts and not isinstance(current, bool):
            errors.append(f"{context}.{field} is required before preflight")


def check_history(stage: dict[str, Any], context: str, errors: list[str]) -> int:
    history = stage.get("evidence_history")
    state = stage.get("evidence_state")
    if state not in EVIDENCE_STATES:
        errors.append(f"{context}.evidence_state must be an ordered catalog state")
        return -1
    if not isinstance(history, list) or not history:
        errors.append(f"{context}.evidence_history must be a non-empty array")
        return -1
    if history[0] != "catalogued" or history[-1] != state:
        errors.append(f"{context}.evidence history must start catalogued and end at evidence_state")
        return -1
    expected_indexes = list(range(len(history)))
    indexes = [EVIDENCE_STATES.index(item) if item in EVIDENCE_STATES else -1 for item in history]
    if indexes != expected_indexes:
        errors.append(f"{context}.evidence history may not skip, repeat, or reorder states")
        return -1
    return indexes[-1]


def check_artifact_types(value: Any, context: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{context} must be a non-empty array of portable artifact types")
        return
    if any(not portable_identifier(item, slug=True) for item in value):
        errors.append(f"{context} contains an unsafe artifact type")
        return
    if len(set(value)) != len(value):
        errors.append(f"{context} must not repeat artifact types")


def validate(ledger: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(ledger, dict):
        return ["ledger root must be an object"]
    check_exact_keys(ledger, "ledger", allowed=ROOT_KEYS, errors=errors)
    if ledger.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")
    if not portable_identifier(ledger.get("campaign_id"), slug=True):
        errors.append("campaign_id must be a portable slug")
    mode = ledger.get("mode")
    if mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}")
    claim = ledger.get("claim_ceiling")
    if claim not in CLAIM_CEILINGS:
        errors.append("claim_ceiling is invalid")
    if mode == "plan" and claim != "plan-only":
        errors.append("plan mode may not claim above plan-only")
    data_classification = ledger.get("data_classification")
    if data_classification not in {"public", "private", "restricted"}:
        errors.append("data_classification must be public, private, or restricted")
    if not isinstance(ledger.get("private_data_authorized"), bool):
        errors.append("private_data_authorized must be a boolean")
    if ledger.get("ready") is True or ledger.get("readiness") in {"ready", "approved"}:
        errors.append("qualification ledger asserts readiness; record an evidence state instead")

    unpriced_work = ledger.get("unpriced_work")
    if not isinstance(unpriced_work, list) or any(not isinstance(item, str) or not item for item in unpriced_work):
        errors.append("unpriced_work must be an array of explanations")
    if mode == "execute" and unpriced_work:
        errors.append("execute mode retains unpriced work; record price facts before execution")

    stages = ledger.get("stages")
    if not isinstance(stages, list) or not stages:
        errors.append("stages must be a non-empty array")
        stages = []
    stage_ids: set[str] = set()
    stage_state_indexes: list[int] = []
    for index, stage_value in enumerate(stages):
        context = f"stages[{index}]"
        stage = check_exact_keys(stage_value, context, allowed=STAGE_KEYS, errors=errors)
        stage_id = stage.get("stage_id")
        if not portable_identifier(stage_id, slug=True):
            errors.append(f"{context}.stage_id must be a portable slug")
        elif stage_id in stage_ids:
            errors.append("stage_id values must be unique")
        else:
            stage_ids.add(stage_id)
        state_index = check_history(stage, context, errors)
        stage_state_indexes.append(state_index)
        is_bound = state_index >= EVIDENCE_STATES.index("bound")
        needs_qualification = state_index >= EVIDENCE_STATES.index("preflight-passed")
        if state_index >= EVIDENCE_STATES.index("executed") and mode != "execute":
            errors.append(f"{context}: executed evidence requires mode=execute")
        for field in ("capability", "adapter", "source", "model", "weights", "runtime"):
            check_identity(stage.get(field), f"{context}.{field}", allow_unknown=not is_bound, errors=errors)
        licenses = check_exact_keys(stage.get("licenses"), f"{context}.licenses", allowed=set(LICENSE_KINDS), errors=errors)
        if set(licenses) != set(LICENSE_KINDS):
            errors.append(f"{context}.licenses must contain code, weights, and service facts")
        for kind in LICENSE_KINDS:
            check_license(licenses.get(kind), f"{context}.licenses.{kind}", require_facts=needs_qualification, errors=errors)

        route_kind = stage.get("route_kind")
        provider = stage.get("provider")
        egress_class = stage.get("egress_class")
        if route_kind not in ROUTE_KINDS:
            errors.append(f"{context}.route_kind is invalid")
        if route_kind == "unbound":
            if provider is not None or egress_class != "unprobed":
                errors.append(f"{context}: unbound route requires provider=null and egress_class=unprobed")
        else:
            if not isinstance(provider, str) or not provider or provider == route_kind:
                errors.append(f"{context}.provider must identify a provider, not the route kind")
            elif not portable_identifier(provider):
                errors.append(f"{context}.provider must be a portable identifier")
            expected_egress = "remote-external" if route_kind in REMOTE_ROUTE_KINDS else "local-only"
            if egress_class != expected_egress:
                errors.append(f"{context}.egress_class does not match route kind")
        if egress_class not in EGRESS_CLASSES:
            errors.append(f"{context}.egress_class is invalid")
        if route_kind in REMOTE_ROUTE_KINDS and data_classification != "public" and ledger.get("private_data_authorized") is not True:
            errors.append(f"{context}: private or restricted remote egress requires private_data_authorized=true")

        price = check_exact_keys(stage.get("price"), f"{context}.price", allowed=PRICE_KEYS, errors=errors)
        if price.get("confidence") not in {"unknown", "low", "medium", "high"}:
            errors.append(f"{context}.price.confidence is invalid")
        if price.get("source") is not None and not isinstance(price.get("source"), str):
            errors.append(f"{context}.price.source must be a string or null")
        elif price.get("source") is not None and SOURCE_REFERENCE_RE.fullmatch(price["source"]) is None:
            errors.append(f"{context}.price.source must be a safe source reference or null")
        if price.get("estimate_usd") is not None and not non_negative_number(price.get("estimate_usd")):
            errors.append(f"{context}.price.estimate_usd must be null or non-negative")
        if needs_qualification and (not present(price.get("source")) or price.get("estimate_usd") is None or price.get("confidence") == "unknown"):
            errors.append(f"{context}: preflight requires price source, estimate, and confidence")
        if mode == "execute" and (price.get("estimate_usd") is None or price.get("confidence") == "unknown"):
            errors.append(f"{context}: execute mode requires priced work")

        check_artifact_types(stage.get("input_artifact_types"), f"{context}.input_artifact_types", errors)
        check_artifact_types(stage.get("output_artifact_types"), f"{context}.output_artifact_types", errors)
        if state_index >= EVIDENCE_STATES.index("artifact-validated") and stage.get("artifact_validation") is not True:
            errors.append(f"{context}: artifact-validated state requires artifact_validation=true")
        if state_index < EVIDENCE_STATES.index("artifact-validated") and stage.get("artifact_validation") is not False:
            errors.append(f"{context}: artifact_validation must remain false before artifact validation")

    if mode == "execute" and any(
        state_index < EVIDENCE_STATES.index("preflight-passed") for state_index in stage_state_indexes
    ):
        errors.append("execute mode requires preflight-passed evidence for every stage")

    required_state = CLAIM_MINIMUM_STATE.get(claim)
    if required_state and any(
        state_index < EVIDENCE_STATES.index(required_state) for state_index in stage_state_indexes
    ):
        errors.append(f"{claim} requires {required_state} evidence for every stage")
    if claim == "cross-model-supported":
        errors.append(
            "cross-model-supported is unavailable because this ledger has no independent model-family evidence"
        )

    errors.extend(secret_findings(ledger))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--json", action="store_true", help="emit a JSON result")
    args = parser.parse_args()
    try:
        value = strict_json.loads(args.ledger.read_bytes())
    except (OSError, strict_json.StrictJSONError) as exc:
        errors = [f"cannot load ledger: {exc}"]
    else:
        errors = validate(value)
    result = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}")
    else:
        print(f"Qualification ledger is valid: {args.ledger}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
