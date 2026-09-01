#!/usr/bin/env python3
"""Validate a Codex Binder Lane campaign decision contract."""

from __future__ import annotations

import argparse
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


ALLOWED_MODES = {"plan", "dry-run", "execute"}
ALLOWED_POSTURES = {
    "reproduce",
    "approximate-reproduction",
    "deliberate-swap",
    "best-available",
}
ALLOWED_EXECUTION_SCOPES = {
    "custom-campaign",
    "deposited-complex-evaluation",
    "full-campaign",
    "technical-canary",
}
FULL_CAMPAIGN_COVERAGE = {
    "target-site-preparation": {"target-preparation", "target-site-preparation"},
    "generation-or-codesign": {
        "backbone-generation",
        "binder-generation",
        "codesign",
        "sequence-design",
    },
    "independent-complex-prediction": {
        "complex-prediction",
        "independent-complex-prediction",
        "independent-validation",
        "validation",
    },
    "interface-and-control-scoring": {
        "interface-scoring",
        "control-scoring",
        "scoring",
    },
    "diversity-novelty-developability": {
        "developability",
        "diversity-analysis",
        "diversity-novelty-developability",
        "novelty-analysis",
    },
    "promotion": {"promotion", "candidate-promotion"},
    "final-report": {"final-report", "reporting", "delivery-closeout"},
}
ALLOWED_STAGE_COVERAGE = set(FULL_CAMPAIGN_COVERAGE)
ALLOWED_DIRECTIONS = {"maximize", "minimize"}
ALLOWED_CLAIMS = {
    "plan-only",
    "transport-proven",
    "computational-candidate",
    "cross-model-supported",
}
SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "secret",
    "secret_key",
    "token",
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
    "manual-handoff",
}
REMOTE_ROUTE_KINDS = ALLOWED_ROUTE_KINDS - {"local"}
ALLOWED_ESTIMATE_STATUSES = {"unknown", "dry-run", "estimated", "quoted", "observed"}
ALLOWED_STOP_CONDITIONS = {
    "authorization-boundary",
    "budget",
    "calibrated-target",
    "cleanup-failure",
    "control-failure",
    "diversity-collapse",
    "missing-provenance",
    "no-improvement",
    "round-cap",
    "wall-clock",
    "zero-passers",
}
PRESENTATION_POSTURES = {"preferred", "required", "required-by-user", "not-requested"}
PRESENTATION_SCOPES = {
    "sequence_scope": {"all-generated", "delivered", "not-applicable"},
    "structure_scope": {"all-predicted", "promoted", "not-applicable"},
}
HTML_VERIFICATION_POSTURES = {"required", "not-applicable"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
STAGE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_OVERLAY_OUTPUT_FILES = 4094
MAX_OVERLAY_OUTPUT_BYTES = 640 * 1024 * 1024
MAX_OVERLAY_ARTIFACT_BYTES = 512 * 1024 * 1024


def present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def finite_positive(value: Any, *, allow_zero: bool = False) -> bool:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return False
    return value >= 0 if allow_zero else value > 0


def whole_number(value: Any, *, allow_zero: bool = False) -> bool:
    return finite_positive(value, allow_zero=allow_zero) and float(value).is_integer()


def sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def choice(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def secret_key_name(value: str) -> bool:
    return value in SECRET_KEYS or value.endswith(
        (
            "_access_token",
            "_api_key",
            "_client_secret",
            "_password",
            "_secret",
            "_token",
        )
    )


def at(root: Any, *keys: str, default: Any = None) -> Any:
    current = root
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def secret_findings(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            reference_field = normalized.endswith(("_env_key", "_environment_key"))
            secret_like = secret_key_name(normalized) or reference_field
            symbolic_reference = (
                reference_field
                and isinstance(child, str)
                and ENV_KEY_RE.fullmatch(child) is not None
            )
            if secret_like and not symbolic_reference and present(child):
                findings.append(
                    f"{path}.{key} appears to contain a secret; store only an environment-key name"
                )
            findings.extend(secret_findings(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(secret_findings(child, f"{path}[{index}]"))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        query_keys = {
            key.lower().replace("-", "_")
            for key, _ in parse_qsl(urlsplit(value).query, keep_blank_values=True)
        }
        if any(
            secret_key_name(key) or key in {"key", "sig", "signature"}
            for key in query_keys
        ):
            findings.append(f"{path} contains a credential-like URL query parameter")
    return findings


def validate(plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if plan.get("schema_version") != "codex-binder-lane/v1":
        errors.append("schema_version must equal codex-binder-lane/v1")
    if not present(plan.get("campaign_id")):
        errors.append("campaign_id is required")
    mode = plan.get("mode")
    if not choice(mode, ALLOWED_MODES):
        errors.append(f"mode must be one of {sorted(ALLOWED_MODES)}")

    if not present(at(plan, "purpose", "research_aim")):
        errors.append("purpose.research_aim is required")
    if not present(at(plan, "purpose", "intended_use")):
        warnings.append("purpose.intended_use is unresolved")
    if mode == "execute" and not present(at(plan, "purpose", "safety_assessment")):
        errors.append("purpose.safety_assessment is required for execute mode")

    for field in ("identifier", "construct", "source", "structure_or_sequence"):
        if not present(at(plan, "target", field)):
            errors.append(f"target.{field} is required")
    site_mode = at(plan, "target", "site", "mode")
    if not choice(
        site_mode,
        {
            "explicit-residues",
            "reference-interface",
            "pose-derived",
            "spatial-patch",
            "unconstrained-discovery",
        },
    ):
        errors.append("target.site.mode must name a supported site-selection posture")
    if site_mode != "unconstrained-discovery" and not present(
        at(plan, "target", "site", "residues")
    ):
        errors.append(
            "target.site.residues is required unless site mode is unconstrained-discovery"
        )
    site_discovery_campaign = (
        site_mode == "unconstrained-discovery"
        and at(plan, "execution", "scope") == "custom-campaign"
    )
    if (
        choice(mode, {"dry-run", "execute"})
        and site_mode == "unconstrained-discovery"
        and not site_discovery_campaign
    ):
        errors.append(
            "target.site.mode=unconstrained-discovery requires execution.scope=custom-campaign for a site-discovery run; lock the selected site before a full generation campaign"
        )
    elif choice(mode, {"dry-run", "execute"}) and site_discovery_campaign:
        warnings.append(
            "custom site-discovery campaign must emit the selected site and feed a new locked plan before a full generation campaign"
        )
    if not present(at(plan, "target", "site", "numbering_scheme")):
        errors.append("target.site.numbering_scheme is required")
    if not present(at(plan, "target", "site", "evidence")):
        errors.append(
            "target.site.evidence is required, including for an unconstrained choice"
        )
    confidentiality = at(plan, "target", "confidentiality")
    if not choice(confidentiality, {"public", "private", "restricted"}):
        errors.append("target.confidentiality must be public, private, or restricted")
    if mode == "execute":
        if not present(at(plan, "target", "chains")):
            errors.append("target.chains is required for execute mode")

        source_lock = at(plan, "target", "source_lock", default={})
        if not isinstance(source_lock, dict):
            errors.append("target.source_lock must be an object for execute mode")
            source_lock = {}
        for field in ("source_id", "source_version"):
            if not present(source_lock.get(field)):
                errors.append(
                    f"target.source_lock.{field} is required for execute mode"
                )
        for field in ("source_sha256", "input_sha256"):
            if not sha256(source_lock.get(field)):
                errors.append(
                    f"target.source_lock.{field} must be a SHA-256 for execute mode"
                )

        chain_mapping = at(plan, "target", "chain_mapping", default=[])
        if not isinstance(chain_mapping, list) or not chain_mapping:
            errors.append("target.chain_mapping is required for execute mode")
        else:
            source_chains = at(plan, "target", "chains", default=[])
            known_chains = (
                {str(chain) for chain in source_chains}
                if isinstance(source_chains, list)
                else set()
            )
            campaign_chains: set[str] = set()
            mapped_target = False
            for index, mapping in enumerate(chain_mapping):
                if not isinstance(mapping, dict):
                    errors.append(f"target.chain_mapping[{index}] must be an object")
                    continue
                for field in ("source_chain", "campaign_chain", "role"):
                    if not present(mapping.get(field)):
                        errors.append(
                            f"target.chain_mapping[{index}].{field} is required for execute mode"
                        )
                source_chain = mapping.get("source_chain")
                if (
                    known_chains
                    and present(source_chain)
                    and str(source_chain) not in known_chains
                ):
                    errors.append(
                        f"target.chain_mapping[{index}].source_chain must be named in target.chains"
                    )
                campaign_chain = mapping.get("campaign_chain")
                if present(campaign_chain):
                    if str(campaign_chain) in campaign_chains:
                        errors.append(
                            "target.chain_mapping campaign_chain values must be unique"
                        )
                    campaign_chains.add(str(campaign_chain))
                mapped_target = mapped_target or mapping.get("role") == "target"
            if not mapped_target:
                errors.append(
                    "target.chain_mapping must contain one role=target entry for execute mode"
                )

        residue_map = at(plan, "target", "residue_map", default={})
        if not isinstance(residue_map, dict):
            errors.append("target.residue_map must be an object for execute mode")
            residue_map = {}
        if not present(residue_map.get("artifact")):
            errors.append("target.residue_map.artifact is required for execute mode")
        if not sha256(residue_map.get("sha256")):
            errors.append(
                "target.residue_map.sha256 must be a SHA-256 for execute mode"
            )

    length_range = at(plan, "binder", "length_range")
    if (
        not isinstance(length_range, list)
        or len(length_range) != 2
        or not all(whole_number(item) for item in length_range)
        or length_range[0] > length_range[1]
    ):
        errors.append(
            "binder.length_range must be two positive ascending whole numbers"
        )
    if not whole_number(at(plan, "binder", "requested_delivered_count")):
        errors.append(
            "binder.requested_delivered_count must be a positive whole number"
        )

    posture = at(plan, "method", "posture")
    if not choice(posture, ALLOWED_POSTURES):
        errors.append(f"method.posture must be one of {sorted(ALLOWED_POSTURES)}")
    if choice(posture, {"reproduce", "approximate-reproduction"}) and not present(
        at(plan, "method", "reference_stack")
    ):
        errors.append("method.reference_stack is required for reproduction postures")
    if posture == "deliberate-swap" and not present(
        at(plan, "method", "declared_swaps")
    ):
        errors.append("method.declared_swaps is required for deliberate-swap")

    stages = at(plan, "execution", "stages", default=[])
    execution_scope = at(plan, "execution", "scope")
    if choice(mode, {"dry-run", "execute"}) and not present(
        at(plan, "execution", "posture")
    ):
        errors.append("execution.posture is required for dry-run or execute mode")
    if choice(mode, {"dry-run", "execute"}) and not choice(
        execution_scope, ALLOWED_EXECUTION_SCOPES
    ):
        errors.append(
            "execution.scope must explicitly classify the run as one of "
            f"{sorted(ALLOWED_EXECUTION_SCOPES)}"
        )
    if choice(mode, {"dry-run", "execute"}) and not isinstance(stages, list):
        errors.append("execution.stages must be an array")
        stages = []
    if choice(mode, {"dry-run", "execute"}) and not stages:
        errors.append(
            "execution.stages must bind at least one stage for dry-run or execute mode"
        )

    remote = False
    paid = False
    restricted = False
    stage_estimate_total = 0.0
    stage_estimates_exact_zero = isinstance(stages, list) and bool(stages)
    independent_predictor_stages: list[dict[str, Any]] = []
    predictor_model_families: set[str] = set()
    declared_campaign_coverage: set[str] = set()
    resolved_stage_ids: set[str] = set()
    if isinstance(stages, list):
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                errors.append(f"execution.stages[{index}] must be an object")
                stage_estimates_exact_zero = False
                paid = True
                continue
            for field in ("role", "capability"):
                if not present(stage.get(field)):
                    errors.append(f"execution.stages[{index}].{field} is required")
            explicit_stage_id = stage.get("stage_id")
            resolved_stage_id = (
                explicit_stage_id if present(explicit_stage_id) else stage.get("role")
            )
            if not isinstance(resolved_stage_id, str) or STAGE_ID_RE.fullmatch(resolved_stage_id) is None:
                errors.append(
                    f"execution.stages[{index}].stage_id must be a portable lowercase slug when supplied; otherwise role must be one"
                )
            elif resolved_stage_id in resolved_stage_ids:
                errors.append("execution stage IDs must be unique")
            else:
                resolved_stage_ids.add(resolved_stage_id)
            stage_covers = stage.get("covers", [])
            if present(stage_covers):
                if not isinstance(stage_covers, list) or any(
                    not choice(item, ALLOWED_STAGE_COVERAGE) for item in stage_covers
                ):
                    errors.append(
                        f"execution.stages[{index}].covers must contain only "
                        f"{sorted(ALLOWED_STAGE_COVERAGE)}"
                    )
                else:
                    declared_campaign_coverage.update(stage_covers)
            route_kind = stage.get("route_kind")
            legacy_route = stage.get("route")
            if mode == "execute":
                if not present(route_kind):
                    errors.append(
                        f"execution.stages[{index}].route_kind is required for execute mode"
                    )
                if not present(stage.get("provider")):
                    errors.append(
                        f"execution.stages[{index}].provider is required for execute mode"
                    )
                if present(legacy_route):
                    errors.append(
                        f"execution.stages[{index}].route is a legacy field; use route_kind and provider"
                    )
            elif not present(route_kind) and not present(legacy_route):
                errors.append(f"execution.stages[{index}].route_kind is required")
            effective_route = route_kind if present(route_kind) else legacy_route
            if not choice(effective_route, ALLOWED_ROUTE_KINDS):
                errors.append(
                    f"execution.stages[{index}].route_kind must be one of {sorted(ALLOWED_ROUTE_KINDS)}"
                )
            if (
                present(route_kind)
                and present(legacy_route)
                and route_kind != legacy_route
            ):
                errors.append(
                    f"execution.stages[{index}].route and route_kind must agree when both are present"
                )
            if (
                present(stage.get("provider"))
                and stage.get("provider") == effective_route
            ):
                errors.append(
                    f"execution.stages[{index}].provider must identify the provider, not repeat route_kind"
                )
            remote = remote or choice(effective_route, REMOTE_ROUTE_KINDS)
            if mode == "execute" and not isinstance(stage.get("paid"), bool):
                errors.append(
                    f"execution.stages[{index}].paid must be a boolean for execute mode"
                )
            if mode == "execute" and not isinstance(
                stage.get("restricted_license"), bool
            ):
                errors.append(
                    f"execution.stages[{index}].restricted_license must be a boolean for execute mode"
                )
            stage_paid = stage.get("paid")
            paid = paid or stage_paid is not False
            restricted = restricted or stage.get("restricted_license") is not False
            if mode == "execute":
                stage_estimate = stage.get("estimated_cost_usd")
                if not finite_positive(stage_estimate, allow_zero=True):
                    errors.append(
                        f"execution.stages[{index}].estimated_cost_usd must be a non-negative number for execute mode"
                    )
                    stage_estimates_exact_zero = False
                else:
                    stage_estimate_total += float(stage_estimate)
                    if float(stage_estimate) > 0:
                        stage_estimates_exact_zero = False
                        paid = True
                        if stage_paid is False:
                            errors.append(
                                f"execution.stages[{index}].paid cannot be false when estimated_cost_usd is positive"
                            )
            if stage.get("independent_predictor") is True:
                independent_predictor_stages.append(stage)
                if not present(stage.get("model_family")):
                    errors.append(
                        f"execution.stages[{index}].model_family is required for an independent predictor"
                    )
            if choice(
                stage.get("role"),
                {"complex-prediction", "independent-validation", "validation"},
            ):
                if present(stage.get("model_family")):
                    predictor_model_families.add(str(stage["model_family"]))

            role = stage.get("role")
            if isinstance(role, str):
                for coverage, accepted_roles in FULL_CAMPAIGN_COVERAGE.items():
                    if role in accepted_roles:
                        declared_campaign_coverage.add(coverage)

        if execution_scope == "full-campaign":
            roles = {
                stage.get("role")
                for stage in stages
                if isinstance(stage, dict) and isinstance(stage.get("role"), str)
            }
            if "end-to-end-binder-design" not in roles:
                for coverage in sorted(FULL_CAMPAIGN_COVERAGE):
                    if coverage not in declared_campaign_coverage:
                        errors.append(
                            "execution.scope full-campaign is missing declared "
                            f"{coverage} coverage; use a matching role or list it in a stage covers array"
                        )

    artifact_budget = at(plan, "execution", "artifact_budget")
    if artifact_budget is not None:
        if not isinstance(artifact_budget, dict):
            errors.append("execution.artifact_budget must be an object")
        else:
            allowed_budget_keys = {
                "max_output_files_per_overlay",
                "max_output_bytes_per_overlay",
                "max_output_bytes_per_artifact",
            }
            extra_budget_keys = sorted(set(artifact_budget) - allowed_budget_keys)
            if extra_budget_keys:
                errors.append(
                    "execution.artifact_budget contains unsupported keys: "
                    + ", ".join(extra_budget_keys)
                )
            file_limit = artifact_budget.get("max_output_files_per_overlay")
            total_limit = artifact_budget.get("max_output_bytes_per_overlay")
            artifact_limit = artifact_budget.get("max_output_bytes_per_artifact")
            if not whole_number(file_limit) or file_limit > MAX_OVERLAY_OUTPUT_FILES:
                errors.append(
                    "execution.artifact_budget.max_output_files_per_overlay must be an integer from 1 to "
                    f"{MAX_OVERLAY_OUTPUT_FILES}"
                )
            if not whole_number(total_limit) or total_limit > MAX_OVERLAY_OUTPUT_BYTES:
                errors.append(
                    "execution.artifact_budget.max_output_bytes_per_overlay must be an integer from 1 to "
                    f"{MAX_OVERLAY_OUTPUT_BYTES}"
                )
            if not whole_number(artifact_limit) or artifact_limit > MAX_OVERLAY_ARTIFACT_BYTES:
                errors.append(
                    "execution.artifact_budget.max_output_bytes_per_artifact must be an integer from 1 to "
                    f"{MAX_OVERLAY_ARTIFACT_BYTES}"
                )
            if (
                whole_number(total_limit)
                and whole_number(artifact_limit)
                and artifact_limit > total_limit
            ):
                errors.append(
                    "execution.artifact_budget.max_output_bytes_per_artifact cannot exceed max_output_bytes_per_overlay"
                )

    ceiling = at(plan, "budget", "maximum_spend_usd")
    ceiling_is_nonnegative = finite_positive(ceiling, allow_zero=True)
    if mode == "execute" and not ceiling_is_nonnegative:
        errors.append(
            "budget.maximum_spend_usd must be a non-negative number for execute mode"
        )
    estimate = at(plan, "budget", "estimate_usd")
    estimate_is_nonnegative = finite_positive(estimate, allow_zero=True)
    estimate_status = at(plan, "budget", "estimate_status")
    if not choice(estimate_status, ALLOWED_ESTIMATE_STATUSES):
        errors.append(
            f"budget.estimate_status must be one of {sorted(ALLOWED_ESTIMATE_STATUSES)}"
        )
    if mode == "execute" and not estimate_is_nonnegative:
        errors.append(
            "budget.estimate_usd must be a non-negative number for execute mode"
        )
    if mode == "execute" and not choice(estimate_status, {"estimated", "quoted"}):
        errors.append(
            "execute mode requires budget.estimate_status=estimated or quoted"
        )
    if estimate_is_nonnegative and ceiling_is_nonnegative and estimate > ceiling:
        errors.append("budget.estimate_usd exceeds budget.maximum_spend_usd")
    if estimate_is_nonnegative and estimate < stage_estimate_total:
        errors.append(
            "budget.estimate_usd cannot be lower than the sum of execution stage estimates"
        )
    if mode == "execute" and not finite_positive(
        at(plan, "budget", "maximum_wall_clock_hours")
    ):
        errors.append(
            "budget.maximum_wall_clock_hours must be positive for execute mode"
        )
    unpriced = at(plan, "budget", "unpriced_work")
    unpriced_is_list = isinstance(unpriced, list)
    if not unpriced_is_list:
        errors.append("budget.unpriced_work must be an array")
    if mode == "execute" and not unpriced_is_list:
        errors.append("execute mode requires budget.unpriced_work to be an empty array")
    if mode == "execute" and unpriced_is_list and unpriced:
        errors.append("execute mode cannot contain unpriced work")
    if mode == "execute" and estimate_is_nonnegative and float(estimate) > 0:
        paid = True
    if mode == "execute" and ceiling_is_nonnegative and float(ceiling) == 0:
        zero_cost_fully_bound = (
            stage_estimates_exact_zero
            and estimate_is_nonnegative
            and float(estimate) == 0
            and not paid
            and unpriced_is_list
            and not unpriced
        )
        if not zero_cost_fully_bound:
            errors.append(
                "budget.maximum_spend_usd may be zero only when every stage and campaign estimate is exactly zero and no stage is potentially paid or unpriced"
            )
    if (
        mode == "execute"
        and paid
        and at(plan, "authorization", "paid_compute_authorized") is not True
    ):
        errors.append(
            "authorization.paid_compute_authorized must be true for potentially paid execute stages"
        )
    if (
        mode == "execute"
        and restricted
        and at(plan, "authorization", "restricted_license_authorized") is not True
    ):
        errors.append(
            "authorization.restricted_license_authorized must be true for restricted-license stages"
        )
    if (
        mode == "execute"
        and remote
        and confidentiality != "public"
        and at(plan, "authorization", "private_data_authorized") is not True
    ):
        errors.append(
            "authorization.private_data_authorized must be true before remote transfer of non-public target data"
        )

    rounds = at(plan, "search", "maximum_rounds")
    if not whole_number(rounds, allow_zero=True):
        errors.append("search.maximum_rounds must be a non-negative whole number")
    initial_candidates = at(plan, "search", "initial_candidates")
    shortlist = at(plan, "search", "shortlist_for_expensive_validation")
    if present(initial_candidates) and not whole_number(initial_candidates):
        errors.append(
            "search.initial_candidates must be a positive whole number when provided"
        )
    if present(shortlist) and not whole_number(shortlist):
        errors.append(
            "search.shortlist_for_expensive_validation must be a positive whole number when provided"
        )
    if (
        whole_number(initial_candidates)
        and whole_number(shortlist)
        and shortlist > initial_candidates
    ):
        errors.append(
            "search.shortlist_for_expensive_validation cannot exceed search.initial_candidates"
        )
    if isinstance(rounds, (int, float)) and rounds > 0:
        for field in ("parents_per_round", "variants_per_parent"):
            if not whole_number(at(plan, "search", field)):
                errors.append(
                    f"search.{field} must be a positive whole number when maximum_rounds > 0"
                )
        operator = at(plan, "search", "mutating_operator")
        if not present(operator) or str(operator).lower() in {
            "identity",
            "no-op",
            "noop",
            "copy",
        }:
            errors.append(
                "optimization rounds require a non-identity search.mutating_operator"
            )
        if not present(at(plan, "search", "stop_conditions")):
            errors.append("search.stop_conditions is required when maximum_rounds > 0")
    stop_conditions = at(plan, "search", "stop_conditions", default=[])
    if present(stop_conditions):
        if not isinstance(stop_conditions, list) or any(
            not choice(item, ALLOWED_STOP_CONDITIONS) for item in stop_conditions
        ):
            errors.append(
                f"search.stop_conditions must use only {sorted(ALLOWED_STOP_CONDITIONS)}"
            )
    if mode == "execute":
        if not whole_number(initial_candidates):
            errors.append(
                "search.initial_candidates must be a positive whole number for execute mode"
            )
        if not whole_number(shortlist):
            errors.append(
                "search.shortlist_for_expensive_validation is required for execute mode"
            )
        required_stops = {
            "authorization-boundary",
            "budget",
            "missing-provenance",
            "wall-clock",
        }
        if not isinstance(stop_conditions, list) or not required_stops.issubset(
            stop_conditions
        ):
            errors.append(
                "execute mode stop conditions must include authorization-boundary, budget, missing-provenance, and wall-clock"
            )
        if isinstance(rounds, (int, float)) and rounds > 0:
            optimization_stops = {"round-cap", "zero-passers"}
            if not isinstance(stop_conditions, list) or not optimization_stops.issubset(
                stop_conditions
            ):
                errors.append(
                    "optimization stop conditions must include round-cap and zero-passers"
                )

        fanout = at(plan, "search", "evaluation_fanout", default={})
        if not isinstance(fanout, dict):
            errors.append("search.evaluation_fanout must be an object for execute mode")
            fanout = {}
        fanout_fields = (
            "candidate_prediction_seeds",
            "control_evaluations",
            "final_rescore_candidates",
            "final_rescore_seeds",
            "maximum_expensive_evaluations",
        )
        for field in fanout_fields:
            if not whole_number(
                fanout.get(field), allow_zero=field != "candidate_prediction_seeds"
            ):
                errors.append(
                    f"search.evaluation_fanout.{field} must be a whole number for execute mode"
                )
        if all(
            whole_number(
                fanout.get(field), allow_zero=field != "candidate_prediction_seeds"
            )
            for field in fanout_fields
        ) and whole_number(shortlist):
            expected_evaluations = (
                int(shortlist) * int(fanout["candidate_prediction_seeds"])
                + int(fanout["control_evaluations"])
                + int(fanout["final_rescore_candidates"])
                * int(fanout["final_rescore_seeds"])
            )
            if isinstance(rounds, (int, float)) and rounds > 0:
                expected_evaluations += (
                    int(rounds)
                    * int(at(plan, "search", "parents_per_round"))
                    * int(at(plan, "search", "variants_per_parent"))
                    * int(fanout["candidate_prediction_seeds"])
                )
            if fanout["maximum_expensive_evaluations"] < expected_evaluations:
                errors.append(
                    "search.evaluation_fanout.maximum_expensive_evaluations cannot be lower than declared fanout"
                )
    if "no-improvement" in stop_conditions:
        convergence = at(plan, "search", "convergence", default={})
        if not isinstance(convergence, dict):
            errors.append(
                "search.convergence must be an object when no-improvement is a stop condition"
            )
        else:
            if not finite_positive(
                convergence.get("minimum_improvement_delta"), allow_zero=True
            ):
                errors.append(
                    "search.convergence.minimum_improvement_delta must be non-negative for no-improvement"
                )
            if not whole_number(convergence.get("consecutive_rounds")):
                errors.append(
                    "search.convergence.consecutive_rounds must be a positive whole number for no-improvement"
                )

    metric = at(plan, "objective", "primary_metric")
    direction = at(plan, "objective", "direction")
    if choice(mode, {"dry-run", "execute"}) and not present(metric):
        errors.append(
            "objective.primary_metric is required for dry-run or execute mode"
        )
    if not choice(direction, ALLOWED_DIRECTIONS):
        errors.append(
            f"objective.direction must be one of {sorted(ALLOWED_DIRECTIONS)}"
        )
    if choice(mode, {"dry-run", "execute"}) and not present(
        at(plan, "objective", "aggregation")
    ):
        errors.append("objective.aggregation is required for dry-run or execute mode")
    ranking_status = at(plan, "objective", "ranking_status")
    if not choice(ranking_status, {"unranked", "provisional", "calibrated"}):
        errors.append(
            "objective.ranking_status must be unranked, provisional, or calibrated"
        )
    calibration = at(plan, "objective", "calibration_status")
    controls = at(plan, "objective", "controls", default={})
    if ranking_status == "calibrated":
        if calibration != "target-specific-passed":
            errors.append(
                "calibrated ranking requires objective.calibration_status=target-specific-passed"
            )
        if (
            not isinstance(controls, dict)
            or not present(controls.get("positive"))
            or not present(controls.get("negative"))
        ):
            errors.append("calibrated ranking requires positive and negative controls")
        calibration_evidence = at(plan, "objective", "calibration_evidence", default={})
        if not isinstance(calibration_evidence, dict):
            errors.append("calibrated ranking requires objective.calibration_evidence")
            calibration_evidence = {}
        for field in (
            "target_input_sha256",
            "pipeline_sha256",
            "positive_control_results_sha256",
            "negative_control_results_sha256",
        ):
            if not sha256(calibration_evidence.get(field)):
                errors.append(
                    f"objective.calibration_evidence.{field} must be a SHA-256 for calibrated ranking"
                )
        if calibration_evidence.get("separation_passed") is not True:
            errors.append(
                "calibrated ranking requires objective.calibration_evidence.separation_passed=true"
            )
        locked_target_hash = at(plan, "target", "source_lock", "input_sha256")
        if (
            sha256(locked_target_hash)
            and calibration_evidence.get("target_input_sha256") != locked_target_hash
        ):
            errors.append(
                "calibration evidence must lock to target.source_lock.input_sha256"
            )

    claim = at(plan, "evidence", "claim_ceiling")
    if not choice(claim, ALLOWED_CLAIMS):
        errors.append(f"evidence.claim_ceiling must be one of {sorted(ALLOWED_CLAIMS)}")
    if choice(mode, {"plan", "dry-run"}) and claim != "plan-only":
        errors.append("plan and dry-run mode claim ceilings must remain plan-only")
    if claim == "cross-model-supported" and ranking_status != "calibrated":
        errors.append("cross-model-supported claim requires calibrated ranking")
    if claim == "cross-model-supported" and len(predictor_model_families) < 2:
        errors.append(
            "cross-model-supported claim requires at least two distinct predictor model families"
        )
    if claim == "cross-model-supported" and not independent_predictor_stages:
        errors.append(
            "cross-model-supported claim requires an explicitly independent predictor stage"
        )
    if (
        mode == "execute"
        and at(plan, "evidence", "independent_predictor_required") is True
    ):
        if not independent_predictor_stages:
            errors.append(
                "execute mode requires an execution stage marked independent_predictor when evidence.independent_predictor_required=true"
            )
    if mode == "execute" and not present(at(plan, "evidence", "expected_artifacts")):
        errors.append("evidence.expected_artifacts is required for execute mode")
    presentation = at(plan, "evidence", "presentation", default={})
    if present(presentation) and not isinstance(presentation, dict):
        errors.append("evidence.presentation must be an object")
    elif isinstance(presentation, dict):
        posture_fields = (
            "structure_review",
            "sequence_review",
            "html_report",
            "sequence_visibility",
            "structure_visuals",
            "video",
        )
        for field in posture_fields:
            value = presentation.get(field)
            if present(value) and not choice(value, PRESENTATION_POSTURES):
                errors.append(
                    f"evidence.presentation.{field} must be one of {sorted(PRESENTATION_POSTURES)}"
                )
        if mode == "execute":
            for field in posture_fields:
                if not present(presentation.get(field)):
                    errors.append(
                        f"execute mode requires evidence.presentation.{field}"
                    )
            for field, allowed in PRESENTATION_SCOPES.items():
                if not choice(presentation.get(field), allowed):
                    errors.append(
                        f"evidence.presentation.{field} must be one of {sorted(allowed)}"
                    )
            if not choice(
                presentation.get("browser_verification"),
                HTML_VERIFICATION_POSTURES,
            ):
                errors.append(
                    "evidence.presentation.browser_verification must be required or not-applicable"
                )
            if (
                presentation.get("html_report") != "not-requested"
                and presentation.get("browser_verification") != "required"
            ):
                errors.append(
                    "an HTML report requires evidence.presentation.browser_verification=required"
                )
            if (
                presentation.get("html_report") == "not-requested"
                and presentation.get("browser_verification") != "not-applicable"
            ):
                errors.append(
                    "browser verification must be not-applicable when no HTML report is requested"
                )
            if (
                presentation.get("sequence_review") in {"required", "required-by-user"}
                and presentation.get("sequence_visibility")
                != presentation.get("sequence_review")
            ):
                errors.append(
                    "user-required sequence review requires user-required sequence visibility"
                )
            if (
                presentation.get("structure_review") in {"required", "required-by-user"}
                and presentation.get("structure_visuals")
                != presentation.get("structure_review")
            ):
                errors.append(
                    "user-required structure review requires user-required structure visuals"
                )
            if (
                presentation.get("video") == "required-by-user"
                and presentation.get("html_report") == "not-requested"
            ):
                errors.append("a user-required video requires an HTML report delivery")
            if at(plan, "execution", "scope") == "full-campaign":
                for field in ("html_report", "sequence_visibility", "structure_visuals"):
                    if presentation.get(field) not in {"required", "required-by-user"}:
                        errors.append(
                            f"full-campaign execute mode requires evidence.presentation.{field} to be required"
                        )
            fallbacks = presentation.get("portable_fallbacks")
            if (
                not isinstance(fallbacks, list)
                or not fallbacks
                or any(
                    not isinstance(item, str) or not item.strip() for item in fallbacks
                )
            ):
                errors.append(
                    "execute mode requires string evidence.presentation.portable_fallbacks so viewer availability is not a result dependency"
                )
    if mode == "execute" and present(plan.get("blockers")):
        errors.append("execute mode cannot retain unresolved blockers")

    errors.extend(secret_findings(plan))
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = strict_json.loads(args.plan.read_bytes())
    except (OSError, strict_json.StrictJSONError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": []}, indent=2))
        return 1
    if not isinstance(payload, dict):
        errors, warnings = ["plan root must be a JSON object"], []
    else:
        errors, warnings = validate(payload)
    result = {"ok": not errors, "errors": errors, "warnings": warnings}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("PASS" if not errors else "FAIL")
        for message in errors:
            print(f"ERROR: {message}")
        for message in warnings:
            print(f"WARNING: {message}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
