#!/usr/bin/env python3
"""Build a deterministic, non-biological Binder Lane transport canary bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any


CAMPAIGN_ID = "synthetic-transport-canary"
CANDIDATE_ID = "SYN-CANARY-001"
CLAIM_CEILING = "transport-proven"
FIXTURE_KIND = "software-only-transport-canary"
COUNT_SEMANTICS = "transport-artifacts-only"
FIXED_TIMESTAMP = "2000-01-01T00:00:00Z"
SOURCE_BYTES = b"synthetic-fixture-source-v1\n"


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def csv_bytes(header: list[str], rows: list[list[Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def residue_map_bytes() -> bytes:
    return csv_bytes(
        [
            "source_chain_id",
            "author_residue_number",
            "insertion_code",
            "campaign_chain_id",
            "campaign_residue_number",
            "residue_name",
            "meaning",
        ],
        [["A", 1, "", "A", 1, "UNK", "software-sentinel-only"]],
    )


def synthetic_cif_bytes() -> bytes:
    return (
        "data_SYNTHETIC_PLACEHOLDER\n"
        "_entry.id SYNTHETIC_PLACEHOLDER\n"
        "_struct.title 'NON-BIOLOGICAL SOFTWARE SENTINEL'\n"
        "loop_\n"
        "_atom_site.group_PDB\n"
        "_atom_site.id\n"
        "_atom_site.type_symbol\n"
        "_atom_site.label_atom_id\n"
        "_atom_site.label_comp_id\n"
        "_atom_site.label_asym_id\n"
        "_atom_site.label_seq_id\n"
        "_atom_site.Cartn_x\n"
        "_atom_site.Cartn_y\n"
        "_atom_site.Cartn_z\n"
        "ATOM 1 C CA UNK A 1 0.000 0.000 0.000\n"
        "#\n"
    ).encode("ascii")


def artifact_ref(path: str, payloads: dict[str, bytes]) -> dict[str, Any]:
    data = payloads[path]
    return {"path": path, "sha256": sha256_bytes(data), "size_bytes": len(data)}


def write_payloads(destination: Path, payloads: dict[str, bytes]) -> None:
    for relative_path in sorted(payloads):
        output = destination / relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payloads[relative_path])


def base_plan(target_lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "codex-binder-lane/v1",
        "campaign_id": CAMPAIGN_ID,
        "mode": "execute",
        "fixture": {
            "kind": FIXTURE_KIND,
            "non_biological": True,
            "deterministic": True,
        },
        "purpose": {
            "research_aim": "Exercise portable artifact, receipt, handoff, and hash contracts.",
            "intended_use": "Software validation only",
            "commercial_posture": "not-applicable",
            "safety_assessment": "Contains only public, non-biological sentinel data.",
        },
        "target": {
            "identifier": "SYNTHETIC-PLACEHOLDER",
            "construct": "non-biological-sentinel",
            "source": "deterministic fixture builder",
            "structure_or_sequence": "structures/synthetic-placeholder.cif",
            "chains": ["A"],
            "confidentiality": "public",
            "source_lock": {
                "source_id": "synthetic-fixture-source",
                "source_version": "v1",
                "source_sha256": sha256_bytes(SOURCE_BYTES),
                "source_size_bytes": len(SOURCE_BYTES),
                "input_sha256": sha256_bytes(synthetic_cif_bytes()),
                "input_size_bytes": len(synthetic_cif_bytes()),
            },
            "chain_mapping": [
                {"source_chain": "A", "campaign_chain": "A", "role": "target"}
            ],
            "residue_map": {
                "artifact": "structures/residue-map.csv",
                "sha256": sha256_bytes(residue_map_bytes()),
            },
            "site": {
                "mode": "explicit-residues",
                "residues": ["A:1"],
                "numbering_scheme": "synthetic fixture numbering",
                "evidence": "Software sentinel; no scientific interpretation.",
            },
            "target_lock": target_lock,
        },
        "binder": {
            "modality": "synthetic-sentinel",
            "length_range": [4, 4],
            "requested_delivered_count": 1,
            "constraints": ["non-biological-placeholder-only"],
        },
        "method": {
            "posture": "best-available",
            "reference_stack": None,
            "declared_swaps": [],
        },
        "execution": {
            "scope": "technical-canary",
            "posture": "local-deterministic-fixture",
            "stages": [
                {
                    "role": "fixture-artifact-emission",
                    "capability": "binder-lane-synthetic-fixture",
                    "route_kind": "local",
                    "provider": "synthetic-fixture-emitter",
                    "paid": False,
                    "restricted_license": False,
                    "estimated_cost_usd": 0,
                },
                {
                    "role": "bundle-validation",
                    "capability": "binder-lane-bundle-validator",
                    "route_kind": "local",
                    "provider": "synthetic-bundle-validator",
                    "paid": False,
                    "restricted_license": False,
                    "estimated_cost_usd": 0,
                },
            ],
            "fallbacks": [],
        },
        "budget": {
            "maximum_spend_usd": 0.01,
            "maximum_wall_clock_hours": 0.1,
            "estimate_usd": 0,
            "estimate_status": "estimated",
            "unpriced_work": [],
        },
        "authorization": {
            "paid_compute_authorized": False,
            "private_data_authorized": False,
            "restricted_license_authorized": False,
        },
        "search": {
            "initial_candidates": 1,
            "shortlist_for_expensive_validation": 1,
            "maximum_rounds": 0,
            "parents_per_round": 0,
            "variants_per_parent": 0,
            "mutating_operator": None,
            "stop_conditions": [
                "authorization-boundary",
                "budget",
                "missing-provenance",
                "wall-clock",
            ],
            "evaluation_fanout": {
                "candidate_prediction_seeds": 1,
                "control_evaluations": 0,
                "final_rescore_candidates": 0,
                "final_rescore_seeds": 0,
                "maximum_expensive_evaluations": 1,
            },
        },
        "objective": {
            "primary_metric": "fixture_transport_valid",
            "direction": "maximize",
            "aggregation": "single deterministic fixture",
            "target_threshold": 1,
            "calibration_status": "fixture-only-not-scientific",
            "ranking_status": "unranked",
            "secondary_metrics": [],
            "diversity_constraints": [],
            "controls": {"positive": [], "negative": []},
        },
        "evidence": {
            "independent_predictor_required": False,
            "expected_artifacts": [
                "FASTA",
                "A3M",
                "PDB",
                "mmCIF",
                "metrics",
                "receipts",
                "report",
                "viewer-handoffs",
                "media-handoffs",
            ],
            "presentation": {
                "structure_review": "preferred",
                "sequence_review": "preferred",
                "html_report": "preferred",
                "sequence_visibility": "preferred",
                "structure_visuals": "preferred",
                "video": "not-requested",
                "browser_verification": "required",
                "sequence_scope": "all-generated",
                "structure_scope": "all-predicted",
                "portable_fallbacks": [
                    "PDB_or_mmCIF",
                    "FASTA_or_A3M",
                    "CSV_or_JSON_metrics",
                    "Markdown_report",
                ],
            },
            "claim_ceiling": CLAIM_CEILING,
            "retention_destination": "user-supplied-local-directory",
        },
        "blockers": [],
    }


def build_payloads() -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}

    payloads["sequences/synthetic-placeholder.fasta"] = (
        ">SYN-CANARY-001 non-biological software sentinel\nXXXX\n"
    ).encode("ascii")
    payloads["sequences/synthetic-placeholder.a3m"] = (
        ">SYN-CANARY-001 non-biological software sentinel\nXXXX\n"
    ).encode("ascii")
    payloads["sequences/annotations.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-sequence-annotations/v1",
            "campaign_id": CAMPAIGN_ID,
            "records": [
                {
                    "record_id": CANDIDATE_ID,
                    "candidate_id": CANDIDATE_ID,
                    "entity_role": "synthetic-sentinel",
                    "non_biological": True,
                    "annotation": "X-only placeholder; never use as a biological sequence.",
                }
            ],
        }
    )

    payloads["structures/synthetic-placeholder.pdb"] = (
        "HEADER    SOFTWARE FIXTURE ONLY                   01-JAN-00   SYN0\n"
        "TITLE     NON-BIOLOGICAL SENTINEL COORDINATE RECORD\n"
        "REMARK   1 NO SCIENTIFIC OR STRUCTURAL INTERPRETATION\n"
        "ATOM      1  CA  UNK A   1       0.000   0.000   0.000  1.00  0.00           C  \n"
        "TER       2      UNK A   1\n"
        "END\n"
    ).encode("ascii")
    payloads["structures/synthetic-placeholder.cif"] = synthetic_cif_bytes()
    payloads["structures/residue-map.csv"] = residue_map_bytes()
    payloads["locks/target-site.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-target-site-lock/v1",
            "campaign_id": CAMPAIGN_ID,
            "target_id": "SYNTHETIC-PLACEHOLDER",
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "confidentiality": "public",
            "source_lock": {
                "source_id": "synthetic-fixture-source",
                "source_version": "v1",
                "source_sha256": sha256_bytes(SOURCE_BYTES),
                "source_size_bytes": len(SOURCE_BYTES),
                "input_sha256": sha256_bytes(synthetic_cif_bytes()),
                "input_size_bytes": len(synthetic_cif_bytes()),
            },
            "primary_input": artifact_ref("structures/synthetic-placeholder.cif", payloads),
            "chains": [
                {
                    "source_chain_id": "A",
                    "campaign_chain_id": "A",
                    "role": "target",
                }
            ],
            "residue_map": artifact_ref("structures/residue-map.csv", payloads),
            "site": {
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
            },
            "claim_ceiling": CLAIM_CEILING,
        }
    )
    target_lock_ref = artifact_ref("locks/target-site.json", payloads)
    payloads["codex-binder-plan.json"] = canonical_json_bytes(base_plan(target_lock_ref))

    counts = {
        "requested": 1,
        "produced": 1,
        "parsed": 1,
        "valid": 1,
        "passed": 1,
        "promoted": 0,
        "delivered": 1,
    }
    payloads["metrics/candidates.csv"] = csv_bytes(
        [
            "candidate_id",
            "fixture_transport_valid",
            "scientific_score",
            "scientific_confidence",
            "ranking_status",
        ],
        [[CANDIDATE_ID, 1, "", "", "unranked"]],
    )
    payloads["metrics/metrics.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-metrics/v1",
            "campaign_id": CAMPAIGN_ID,
            "count_semantics": COUNT_SEMANTICS,
            "counts": counts,
            "ranking_status": "unranked",
            "definitions": [
                {
                    "metric_id": "fixture_transport_valid",
                    "evidence_class": "transport",
                    "direction": "maximize",
                    "unit": "boolean",
                },
                {
                    "metric_id": "scientific_confidence",
                    "evidence_class": "scientific",
                    "direction": "maximize",
                    "unit": None,
                },
                {
                    "metric_id": "scientific_score",
                    "evidence_class": "scientific",
                    "direction": "maximize",
                    "unit": None,
                },
            ],
            "records": [
                {
                    "candidate_id": CANDIDATE_ID,
                    "fixture_transport_valid": 1,
                    "scientific_score": None,
                    "scientific_confidence": None,
                    "ranking_status": "unranked",
                    "values": {
                        "fixture_transport_valid": 1,
                        "scientific_confidence": None,
                        "scientific_score": None,
                    },
                    "states": {
                        "fixture_transport_valid": "measured",
                        "scientific_confidence": "not-measured",
                        "scientific_score": "not-measured",
                    },
                }
            ],
        }
    )
    payloads["lineage/candidates.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-lineage/v1",
            "campaign_id": CAMPAIGN_ID,
            "candidates": [
                {
                    "candidate_id": CANDIDATE_ID,
                    "kind": "synthetic-sentinel",
                    "parent_ids": [],
                    "round": 0,
                    "operation": "deterministic-fixture-emission",
                    "status": "transport-valid",
                    "artifact_paths": [
                        "sequences/synthetic-placeholder.fasta",
                        "sequences/synthetic-placeholder.a3m",
                        "structures/synthetic-placeholder.pdb",
                        "structures/synthetic-placeholder.cif",
                    ],
                }
            ],
        }
    )

    payloads["viewer/structure-handoff.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-structure-handoff/v1",
            "campaign_id": CAMPAIGN_ID,
            "candidate_id": CANDIDATE_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "target_lock": target_lock_ref,
            "review_surface": "structure-viewer:structure-viewer",
            "execution_state": {
                "packet": "emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
            },
            "output_artifacts": [],
            "coordinate_artifacts": [
                {
                    **artifact_ref("structures/synthetic-placeholder.pdb", payloads),
                    "format": "pdb",
                    "media_type": "chemical/x-pdb",
                },
                {
                    **artifact_ref("structures/synthetic-placeholder.cif", payloads),
                    "format": "mmcif",
                    "media_type": "chemical/x-mmcif",
                },
            ],
            "residue_map": artifact_ref("structures/residue-map.csv", payloads),
            "chain_roles": {"A": "synthetic-sentinel"},
            "requested_checks": ["file-load", "chain-id", "coordinate-presence"],
            "scientific_interpretation": None,
        }
    )
    payloads["viewer/sequence-handoff.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-sequence-handoff/v1",
            "campaign_id": CAMPAIGN_ID,
            "candidate_id": CANDIDATE_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "target_lock": target_lock_ref,
            "review_surface": "sequence-viewer:biological-sequence-viewer",
            "execution_state": {
                "packet": "emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
            },
            "output_artifacts": [],
            "sequence_artifacts": [
                {
                    **artifact_ref("sequences/synthetic-placeholder.fasta", payloads),
                    "format": "fasta",
                    "media_type": "text/x-fasta",
                },
                {
                    **artifact_ref("sequences/synthetic-placeholder.a3m", payloads),
                    "format": "a3m",
                    "media_type": "text/x-a3m",
                },
            ],
            "annotations": artifact_ref("sequences/annotations.json", payloads),
            "requested_checks": ["file-load", "record-id", "sentinel-only"],
            "scientific_interpretation": None,
        }
    )
    payloads["viewer/portable-review-checklist.md"] = (
        "# Synthetic canary review checklist\n\n"
        "- Confirm both coordinate formats load as one synthetic sentinel atom.\n"
        "- Confirm FASTA and A3M contain only the X-only sentinel record.\n"
        "- Confirm each handoff artifact reference matches `bundle-manifest.json` by path, size, and SHA-256.\n"
        "- Do not interpret this fixture scientifically.\n"
    ).encode("utf-8")

    payloads["media/scenes.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-media-scenes/v1",
            "campaign_id": CAMPAIGN_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "target_lock": target_lock_ref,
            "arbitrary_commands_allowed": False,
            "scenes": [
                {
                    "scene_id": "SYN-SCENE-001",
                    "candidate_id": CANDIDATE_ID,
                    "coordinate_artifact": artifact_ref("structures/synthetic-placeholder.cif", payloads),
                    "selection_preset": "all-sentinel-atoms",
                    "camera": {
                        "projection": "orthographic",
                        "position": [0.0, 0.0, 10.0],
                        "target": [0.0, 0.0, 0.0],
                        "up": [0.0, 1.0, 0.0],
                        "orthographic_scale": 10.0,
                        "clip_near": 0.1,
                        "clip_far": 100.0,
                    },
                    "canvas": {"width": 1280, "height": 720, "background": "#101820"},
                    "scientific_interpretation": None,
                }
            ],
        }
    )
    payloads["media/storyboard.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-media-storyboard/v1",
            "campaign_id": CAMPAIGN_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "fps": 30,
            "width": 1280,
            "height": 720,
            "total_frames": 90,
            "shots": [
                {
                    "shot_id": "SYN-SHOT-001",
                    "scene_id": "SYN-SCENE-001",
                    "start_frame": 0,
                    "duration_frames": 90,
                    "caption": "Software-only, non-biological transport canary",
                    "snapshot_artifact": None,
                }
            ],
        }
    )
    scenes_ref = artifact_ref("media/scenes.json", payloads)
    storyboard_ref = artifact_ref("media/storyboard.json", payloads)
    payloads["media/pymol-handoff.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-renderer-handoff/v1",
            "campaign_id": CAMPAIGN_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "renderer": "pymol",
            "execution_state": {
                "packet": "emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
            },
            "output_artifacts": [],
            "scene_manifest": scenes_ref,
            "required_executable": "pymol",
            "output_pattern": "renders/pymol/{scene_id}.png",
            "arbitrary_commands_allowed": False,
        }
    )
    payloads["media/chimerax-handoff.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-renderer-handoff/v1",
            "campaign_id": CAMPAIGN_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "renderer": "chimerax",
            "execution_state": {
                "packet": "emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
            },
            "output_artifacts": [],
            "scene_manifest": scenes_ref,
            "required_executable": "chimerax",
            "output_pattern": "renders/chimerax/{scene_id}.png",
            "arbitrary_commands_allowed": False,
        }
    )
    payloads["media/remotion-handoff.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-video-handoff/v1",
            "campaign_id": CAMPAIGN_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "framework": "remotion",
            "execution_state": {
                "packet": "emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
            },
            "output_artifacts": [],
            "storyboard": storyboard_ref,
            "asset_policy": "local-staticFile-only",
            "image_component": "Img",
            "timing_policy": "integer-frames-with-premounted-sequences",
            "output_pattern": "renders/remotion/synthetic-transport-canary.mp4",
            "planned_checks": ["props-validated", "midpoint-still", "render-not-run"],
            "network_assets_allowed": False,
        }
    )
    payloads["media/hyperframes-handoff.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-video-handoff/v1",
            "campaign_id": CAMPAIGN_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "claim_ceiling": CLAIM_CEILING,
            "framework": "hyperframes",
            "execution_state": {
                "packet": "emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
            },
            "output_artifacts": [],
            "storyboard": storyboard_ref,
            "composition_id": "synthetic-transport-canary",
            "timeline_policy": "one-paused-seekable-timeline",
            "planned_checks": ["check-strict", "midpoint-snapshot", "preview-approval"],
            "output_pattern": "renders/hyperframes/synthetic-transport-canary.mp4",
            "network_assets_allowed": False,
        }
    )

    plan_ref = artifact_ref("codex-binder-plan.json", payloads)
    portable_outputs = [
        artifact_ref(path, payloads)
        for path in sorted(
            path
            for path in payloads
            if path.startswith(("sequences/", "structures/", "metrics/", "lineage/"))
        )
    ]
    handoff_outputs = [
        artifact_ref(path, payloads)
        for path in sorted(path for path in payloads if path.startswith(("viewer/", "media/")))
    ]

    def receipt(
        receipt_id: str,
        stage_id: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        status: str = "materialized",
    ) -> bytes:
        return canonical_json_bytes(
            {
                "schema_version": "codex-binder-stage-receipt/v1",
                "receipt_id": receipt_id,
                "campaign_id": CAMPAIGN_ID,
                "stage_id": stage_id,
                "attempt": 1,
                "capability": "binder-lane-synthetic-fixture",
                "route_kind": "local",
                "provider": "synthetic-fixture-emitter",
                "status": status,
                "started_at": FIXED_TIMESTAMP,
                "ended_at": FIXED_TIMESTAMP,
                "time_semantics": "deterministic-fixture-sentinel",
                "candidate_ids": [CANDIDATE_ID],
                "parent_ids": [],
                "child_ids": [],
                "inputs": inputs,
                "outputs": outputs,
                "count_semantics": COUNT_SEMANTICS,
                "counts": counts,
                "cost": {"estimate_usd": 0, "observed_usd": 0, "status": "exact-fixture-zero"},
                "cleanup": {"required": False, "status": "not-required"},
                "failure": None,
                "claim_ceiling": CLAIM_CEILING,
            }
        )

    payloads["receipts/00-plan.json"] = receipt(
        "SYN-RECEIPT-00", "plan-materialization", [], [target_lock_ref, plan_ref]
    )
    payloads["receipts/01-portable-artifacts.json"] = receipt(
        "SYN-RECEIPT-01",
        "portable-artifact-emission",
        [target_lock_ref, plan_ref],
        portable_outputs,
    )
    payloads["receipts/02-handoffs.json"] = receipt(
        "SYN-RECEIPT-02",
        "viewer-and-media-handoffs",
        [target_lock_ref, plan_ref, *portable_outputs],
        handoff_outputs,
    )

    payloads["report/summary.json"] = canonical_json_bytes(
        {
            "schema_version": "codex-binder-closeout/v1",
            "campaign_id": CAMPAIGN_ID,
            "candidate_id": CANDIDATE_ID,
            "fixture_kind": FIXTURE_KIND,
            "non_biological": True,
            "assembly_status": "materialized",
            "validation_status": "validator-owned-not-self-attested",
            "claim_ceiling": CLAIM_CEILING,
            "target_lock": target_lock_ref,
            "count_semantics": COUNT_SEMANTICS,
            "counts": counts,
            "ranking_status": "unranked",
            "scientific_score": None,
            "scientific_confidence": None,
            "observed_cost_usd": 0,
            "cost": {"estimate_usd": 0, "observed_usd": 0, "status": "exact-fixture-zero"},
            "cleanup": {"required": False, "status": "not-required"},
            "rendered_snapshot_count": 0,
            "rendered_video_count": 0,
            "receipt_count": 5,
            "receipt_ids": [
                "SYN-RECEIPT-00",
                "SYN-RECEIPT-01",
                "SYN-RECEIPT-02",
                "SYN-RECEIPT-03",
                "SYN-RECEIPT-04",
            ],
            "handoffs": {
                "structure_viewer": {
                    "path": "viewer/structure-handoff.json",
                    "execution_state": {
                        "packet": "emitted",
                        "runtime": "unprobed",
                        "invocation": "not-run",
                        "output_validation": "not-run",
                    },
                    "output_count": 0,
                },
                "sequence_viewer": {
                    "path": "viewer/sequence-handoff.json",
                    "execution_state": {
                        "packet": "emitted",
                        "runtime": "unprobed",
                        "invocation": "not-run",
                        "output_validation": "not-run",
                    },
                    "output_count": 0,
                },
                "pymol": {
                    "path": "media/pymol-handoff.json",
                    "execution_state": {
                        "packet": "emitted",
                        "runtime": "unprobed",
                        "invocation": "not-run",
                        "output_validation": "not-run",
                    },
                    "output_count": 0,
                },
                "chimerax": {
                    "path": "media/chimerax-handoff.json",
                    "execution_state": {
                        "packet": "emitted",
                        "runtime": "unprobed",
                        "invocation": "not-run",
                        "output_validation": "not-run",
                    },
                    "output_count": 0,
                },
                "remotion": {
                    "path": "media/remotion-handoff.json",
                    "execution_state": {
                        "packet": "emitted",
                        "runtime": "unprobed",
                        "invocation": "not-run",
                        "output_validation": "not-run",
                    },
                    "output_count": 0,
                },
                "hyperframes": {
                    "path": "media/hyperframes-handoff.json",
                    "execution_state": {
                        "packet": "emitted",
                        "runtime": "unprobed",
                        "invocation": "not-run",
                        "output_validation": "not-run",
                    },
                    "output_count": 0,
                },
            },
        }
    )
    payloads["report/report.md"] = (
        "# Synthetic Binder Lane transport canary\n\n"
        "> Software-only, non-biological fixture. Claim ceiling: `transport-proven`.\n\n"
        "## Identity and outcome\n\n"
        "The fields below identify this deterministic fixture and its scoped assembly state.\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| Campaign | `synthetic-transport-canary` |\n"
        "| Candidate | `SYN-CANARY-001` |\n"
        "| Fixture | `software-only-transport-canary` |\n"
        "| Bundle assembly | Materialized |\n"
        "| Final validation | Validator-owned; not self-attested by this report |\n"
        "| Observed cost | $0.00 |\n"
        "| Cleanup | Not required |\n\n"
        "## Transport counts\n\n"
        "These are `transport-artifacts-only` record counts. `Passed` does not mean scientific promotion.\n\n"
        "| Stage | Records |\n"
        "| --- | ---: |\n"
        "| Requested | 1 |\n"
        "| Produced | 1 |\n"
        "| Parsed | 1 |\n"
        "| Valid | 1 |\n"
        "| Passed | 1 |\n"
        "| Promoted | 0 |\n"
        "| Delivered | 1 |\n\n"
        "## Evidence boundary\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| Ranking | Unranked |\n"
        "| Scientific score | Not measured |\n"
        "| Scientific confidence | Not measured |\n\n"
        "## Review and media handoffs\n\n"
        "Each row reports packet, capability, invocation, and output state independently.\n\n"
        "| Surface / packet | Packet | Runtime | Invocation | Output validation | Outputs |\n"
        "| --- | --- | --- | --- | --- | ---: |\n"
        "| Structure Viewer — `viewer/structure-handoff.json` | Emitted | Unprobed | Not run | Not run | 0 |\n"
        "| Sequence Viewer — `viewer/sequence-handoff.json` | Emitted | Unprobed | Not run | Not run | 0 |\n"
        "| PyMOL — `media/pymol-handoff.json` | Emitted | Unprobed | Not run | Not run | 0 |\n"
        "| ChimeraX — `media/chimerax-handoff.json` | Emitted | Unprobed | Not run | Not run | 0 |\n"
        "| Remotion — `media/remotion-handoff.json` | Emitted | Unprobed | Not run | Not run | 0 |\n"
        "| HyperFrames — `media/hyperframes-handoff.json` | Emitted | Unprobed | Not run | Not run | 0 |\n\n"
        "## Integrity evidence\n\n"
        "- Artifact manifest: `bundle-manifest.json`\n"
        "- Manifest hash sidecar: `bundle-manifest.sha256`\n"
        "- Target/site lock: `locks/target-site.json`\n"
        "- Stage receipts: five files under `receipts/`\n"
        "- This report does not self-attest final bundle validation; use the bundle validator or builder exit status.\n"
    ).encode("utf-8")
    report_outputs = [
        artifact_ref("report/report.md", payloads),
        artifact_ref("report/summary.json", payloads),
    ]
    payloads["receipts/03-report.json"] = receipt(
        "SYN-RECEIPT-03",
        "report-generation",
        [target_lock_ref, plan_ref, *portable_outputs, *handoff_outputs],
        report_outputs,
    )
    earlier_receipts = [
        artifact_ref(path, payloads)
        for path in (
            "receipts/00-plan.json",
            "receipts/01-portable-artifacts.json",
            "receipts/02-handoffs.json",
            "receipts/03-report.json",
        )
    ]
    payloads["receipts/closeout.json"] = receipt(
        "SYN-RECEIPT-04",
        "bundle-closeout",
        [target_lock_ref, plan_ref, *portable_outputs, *handoff_outputs, *report_outputs, *earlier_receipts],
        [],
        status="assembled-pending-validation",
    )
    return payloads


def build_bundle(destination: Path) -> dict[str, Any]:
    destination = destination.expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination must not exist or must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    payloads = build_payloads()
    write_payloads(destination, payloads)
    file_entries = [
        {
            "path": path,
            "sha256": sha256_bytes(payloads[path]),
            "size_bytes": len(payloads[path]),
        }
        for path in sorted(payloads)
    ]
    metrics = json.loads(payloads["metrics/metrics.json"])
    manifest = {
        "schema_version": "codex-binder-bundle-manifest/v1",
        "campaign_id": CAMPAIGN_ID,
        "fixture_kind": FIXTURE_KIND,
        "claim_ceiling": CLAIM_CEILING,
        "count_semantics": COUNT_SEMANTICS,
        "counts": metrics["counts"],
        "files": file_entries,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    (destination / "bundle-manifest.json").write_bytes(manifest_bytes)
    manifest_hash = sha256_bytes(manifest_bytes)
    (destination / "bundle-manifest.sha256").write_text(
        f"{manifest_hash}  bundle-manifest.json\n", encoding="ascii"
    )

    from validate_bundle import validate_bundle

    errors = validate_bundle(destination)
    if errors:
        raise RuntimeError("fixture bundle failed self-validation: " + "; ".join(errors))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new or empty output directory")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    args = parser.parse_args()
    try:
        manifest = build_bundle(args.destination)
    except (OSError, ValueError, RuntimeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"FAIL: {exc}")
        return 1
    result = {
        "ok": True,
        "destination": str(args.destination.expanduser().resolve()),
        "campaign_id": manifest["campaign_id"],
        "claim_ceiling": manifest["claim_ceiling"],
        "file_count": len(manifest["files"]) + 2,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"PASS: built {result['file_count']} files at {result['destination']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
