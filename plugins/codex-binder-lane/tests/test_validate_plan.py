from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "codex-binder-lane" / "scripts" / "validate_plan.py"
SPEC = importlib.util.spec_from_file_location("validate_plan", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PlanValidationTests(unittest.TestCase):
    def load_valid(self) -> dict:
        path = ROOT / "tests" / "fixtures" / "valid-dry-run-plan.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def make_execute(self) -> dict:
        plan = self.load_valid()
        zeros = "0" * 64
        plan["mode"] = "execute"
        plan["purpose"]["safety_assessment"] = "public synthetic technical canary"
        plan["target"]["source_lock"] = {
            "source_id": "fixture-target",
            "source_version": "v1",
            "source_sha256": zeros,
            "input_sha256": zeros,
        }
        plan["target"]["chain_mapping"] = [
            {"source_chain": "A", "campaign_chain": "T", "role": "target"}
        ]
        plan["target"]["residue_map"] = {
            "artifact": "structures/residue-map.csv",
            "sha256": zeros,
        }
        stage = plan["execution"]["stages"][0]
        stage["estimated_cost_usd"] = 0
        plan["budget"].update(
            {
                "maximum_spend_usd": 1,
                "estimate_usd": 0,
                "estimate_status": "estimated",
            }
        )
        plan["search"].update(
            {
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
                    "maximum_expensive_evaluations": 2,
                },
            }
        )
        plan["evidence"].update(
            {
                "independent_predictor_required": False,
                "expected_artifacts": ["bundle-manifest.json"],
                "claim_ceiling": "transport-proven",
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
                        "PDB",
                        "FASTA",
                        "JSON metrics",
                        "Markdown report",
                    ],
                },
            }
        )
        return plan

    def test_valid_dry_run_contract(self) -> None:
        errors, warnings = MODULE.validate(self.load_valid())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_execute_requires_ceiling_and_authorization(self) -> None:
        plan = self.make_execute()
        plan["budget"]["maximum_spend_usd"] = None
        plan["execution"]["stages"][0]["route_kind"] = "hosted-api"
        plan["execution"]["stages"][0]["provider"] = "fixture-provider"
        plan["execution"]["stages"][0]["paid"] = True
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("maximum_spend_usd" in item for item in errors))
        self.assertTrue(any("paid_compute_authorized" in item for item in errors))

    def test_positive_stage_cost_cannot_bypass_paid_authorization(self) -> None:
        plan = self.make_execute()
        stage = plan["execution"]["stages"][0]
        stage.update({"paid": False, "estimated_cost_usd": 10})
        plan["budget"].update({"maximum_spend_usd": 20, "estimate_usd": 10})
        plan["authorization"]["paid_compute_authorized"] = False

        errors, _ = MODULE.validate(plan)

        self.assertTrue(any("paid cannot be false" in item for item in errors))
        self.assertTrue(any("paid_compute_authorized" in item for item in errors))

        plan["authorization"]["paid_compute_authorized"] = True
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("paid cannot be false" in item for item in errors))
        self.assertFalse(any("paid_compute_authorized" in item for item in errors))

        stage["paid"] = True
        errors, warnings = MODULE.validate(plan)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_positive_campaign_estimate_requires_paid_authorization(self) -> None:
        plan = self.make_execute()
        plan["budget"].update({"maximum_spend_usd": 5, "estimate_usd": 5})
        plan["authorization"]["paid_compute_authorized"] = False

        errors, _ = MODULE.validate(plan)

        self.assertTrue(any("paid_compute_authorized" in item for item in errors))

        plan["authorization"]["paid_compute_authorized"] = True
        errors, warnings = MODULE.validate(plan)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_zero_cost_local_execute_plan_accepts_zero_spend_ceiling(self) -> None:
        plan = self.make_execute()
        plan["budget"]["maximum_spend_usd"] = 0

        errors, warnings = MODULE.validate(plan)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_zero_spend_ceiling_rejects_potentially_paid_or_unpriced_work(self) -> None:
        potentially_paid = self.make_execute()
        potentially_paid["budget"]["maximum_spend_usd"] = 0
        potentially_paid["execution"]["stages"][0]["paid"] = True
        potentially_paid["authorization"]["paid_compute_authorized"] = True

        errors, _ = MODULE.validate(potentially_paid)
        self.assertTrue(any("may be zero only" in item for item in errors))

        for malformed in (None, {}, ""):
            with self.subTest(unpriced_work=malformed):
                malformed_unpriced = self.make_execute()
                malformed_unpriced["budget"]["maximum_spend_usd"] = 0
                malformed_unpriced["budget"]["unpriced_work"] = malformed

                errors, _ = MODULE.validate(malformed_unpriced)

                self.assertTrue(
                    any("unpriced_work must be an array" in item for item in errors)
                )
                self.assertTrue(
                    any(
                        "requires budget.unpriced_work to be an empty array" in item
                        for item in errors
                    )
                )
                self.assertTrue(any("may be zero only" in item for item in errors))

        unpriced = self.make_execute()
        unpriced["budget"]["maximum_spend_usd"] = 0
        unpriced["budget"]["unpriced_work"] = ["provider retry pricing is unresolved"]

        errors, _ = MODULE.validate(unpriced)
        self.assertTrue(any("cannot contain unpriced work" in item for item in errors))
        self.assertTrue(any("may be zero only" in item for item in errors))

        unknown = self.make_execute()
        unknown["budget"]["maximum_spend_usd"] = 0
        unknown["execution"]["stages"][0]["estimated_cost_usd"] = None

        errors, _ = MODULE.validate(unknown)
        self.assertTrue(
            any(
                "estimated_cost_usd must be a non-negative number" in item
                for item in errors
            )
        )
        self.assertTrue(any("may be zero only" in item for item in errors))

    def test_identity_operator_is_not_optimization(self) -> None:
        plan = self.load_valid()
        plan["search"]["mutating_operator"] = "identity"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("non-identity" in item for item in errors))

    def test_calibrated_ranking_requires_controls(self) -> None:
        plan = self.load_valid()
        plan["objective"]["ranking_status"] = "calibrated"
        plan["objective"]["calibration_status"] = "target-specific-passed"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(
            any("positive and negative controls" in item for item in errors)
        )

    def test_malformed_controls_do_not_crash(self) -> None:
        plan = self.load_valid()
        plan["objective"]["ranking_status"] = "calibrated"
        plan["objective"]["calibration_status"] = "target-specific-passed"
        plan["objective"]["controls"] = []
        errors, _ = MODULE.validate(plan)
        self.assertTrue(
            any("positive and negative controls" in item for item in errors)
        )

    def test_private_fal_route_requires_egress_authorization(self) -> None:
        plan = self.make_execute()
        plan["target"]["confidentiality"] = "private"
        stage = plan["execution"]["stages"][0]
        stage.update({"route_kind": "fal", "provider": "fal-ai", "paid": False})
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("private_data_authorized" in item for item in errors))

    def test_execute_contract_can_pass_offline(self) -> None:
        errors, warnings = MODULE.validate(self.make_execute())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        custom_campaign = self.make_execute()
        custom_campaign["execution"]["scope"] = "custom-campaign"
        errors, warnings = MODULE.validate(custom_campaign)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        full_campaign = self.make_execute()
        full_campaign["execution"]["scope"] = "full-campaign"
        errors, _ = MODULE.validate(full_campaign)
        self.assertTrue(any("full-campaign is missing" in item for item in errors))

    def test_full_campaign_accepts_combined_tools_without_fixed_role_names(self) -> None:
        plan = self.make_execute()
        plan["execution"]["scope"] = "full-campaign"
        plan["evidence"]["presentation"].update(
            {
                "html_report": "required",
                "sequence_visibility": "required",
                "structure_visuals": "required",
            }
        )
        stage = plan["execution"]["stages"][0]
        stage["role"] = "provider-native-design-workflow"
        stage["covers"] = sorted(MODULE.ALLOWED_STAGE_COVERAGE)

        errors, warnings = MODULE.validate(plan)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_full_campaign_rejects_unknown_coverage_terms(self) -> None:
        plan = self.make_execute()
        plan["execution"]["scope"] = "full-campaign"
        plan["execution"]["stages"][0]["covers"] = ["magic-binder-score"]

        errors, _ = MODULE.validate(plan)

        self.assertTrue(any("covers must contain only" in item for item in errors))

    def test_counts_must_be_whole_numbers(self) -> None:
        plan = self.load_valid()
        plan["search"]["initial_candidates"] = 1.5
        plan["binder"]["requested_delivered_count"] = 2.5
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("initial_candidates" in item for item in errors))
        self.assertTrue(any("requested_delivered_count" in item for item in errors))

    def test_secret_variants_and_url_api_key_are_rejected(self) -> None:
        plan = self.load_valid()
        plan["execution"]["client_secret"] = "plaintext"
        query_key = "-".join(("api", "key"))
        plan["execution"]["callback"] = (
            "https://example.invalid/job?" + query_key + "=plaintext"
        )
        errors, _ = MODULE.validate(plan)
        self.assertGreaterEqual(
            sum("secret" in item or "credential-like" in item for item in errors), 2
        )

    def test_dry_run_cannot_claim_cross_model_support(self) -> None:
        plan = self.load_valid()
        plan["evidence"]["claim_ceiling"] = "cross-model-supported"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("dry-run" in item for item in errors))

    def test_cross_model_claim_requires_explicit_independent_predictor(self) -> None:
        plan = self.make_execute()
        first_stage = plan["execution"]["stages"][0]
        first_stage.update(
            {
                "role": "complex-prediction",
                "capability": "predictor-a",
                "model_family": "family-a",
            }
        )
        plan["execution"]["stages"].append(
            {
                "role": "complex-prediction",
                "capability": "predictor-b",
                "route_kind": "local",
                "provider": "local-predictor-b",
                "paid": False,
                "restricted_license": False,
                "estimated_cost_usd": 0,
                "model_family": "family-b",
            }
        )
        zeros = "0" * 64
        plan["objective"].update(
            {
                "ranking_status": "calibrated",
                "calibration_status": "target-specific-passed",
                "controls": {"positive": ["positive"], "negative": ["negative"]},
                "calibration_evidence": {
                    "target_input_sha256": zeros,
                    "pipeline_sha256": zeros,
                    "positive_control_results_sha256": zeros,
                    "negative_control_results_sha256": zeros,
                    "separation_passed": True,
                },
            }
        )
        plan["evidence"]["claim_ceiling"] = "cross-model-supported"

        errors, _ = MODULE.validate(plan)
        self.assertTrue(
            any("explicitly independent predictor" in item for item in errors)
        )

        first_stage["independent_predictor"] = True
        errors, _ = MODULE.validate(plan)
        self.assertFalse(
            any("explicitly independent predictor" in item for item in errors)
        )

    def test_optimization_fanout_is_counted(self) -> None:
        plan = self.make_execute()
        plan["search"].update(
            {
                "maximum_rounds": 2,
                "parents_per_round": 2,
                "variants_per_parent": 3,
                "mutating_operator": "fixture-mutation",
                "stop_conditions": [
                    "authorization-boundary",
                    "budget",
                    "missing-provenance",
                    "wall-clock",
                    "round-cap",
                    "zero-passers",
                ],
            }
        )
        plan["search"]["evaluation_fanout"]["maximum_expensive_evaluations"] = 10
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("declared fanout" in item for item in errors))

    def test_restricted_license_must_be_boolean(self) -> None:
        plan = self.make_execute()
        plan["execution"]["stages"][0]["restricted_license"] = "false"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(
            any("restricted_license must be a boolean" in item for item in errors)
        )

    def test_malformed_enums_return_errors(self) -> None:
        for path in (
            ("mode",),
            ("target", "confidentiality"),
            ("objective", "direction"),
        ):
            plan = self.load_valid()
            current = plan
            for key in path[:-1]:
                current = current[key]
            current[path[-1]] = []
            errors, _ = MODULE.validate(plan)
            self.assertTrue(errors)

    def test_env_reference_requires_symbolic_name(self) -> None:
        plan = self.load_valid()
        plan["execution"]["credential_env_key"] = "literal-secret-value"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("appears to contain a secret" in item for item in errors))

    def test_secret_fields_are_rejected(self) -> None:
        plan = self.load_valid()
        plan["execution"]["api_key"] = "not-allowed-in-plan"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("appears to contain a secret" in item for item in errors))

    def test_execute_requires_portable_visual_fallbacks(self) -> None:
        plan = self.make_execute()
        plan["evidence"]["presentation"]["portable_fallbacks"] = []
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("portable_fallbacks" in item for item in errors))

    def test_execute_locks_report_and_visual_delivery_requirements(self) -> None:
        plan = self.make_execute()
        del plan["evidence"]["presentation"]["structure_visuals"]
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("requires evidence.presentation.structure_visuals" in item for item in errors))

    def test_user_required_review_cannot_drop_visible_outputs(self) -> None:
        plan = self.make_execute()
        presentation = plan["evidence"]["presentation"]
        presentation["structure_review"] = "required-by-user"
        presentation["structure_visuals"] = "preferred"
        presentation["sequence_review"] = "required-by-user"
        presentation["sequence_visibility"] = "not-requested"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("structure review" in item for item in errors))
        self.assertTrue(any("sequence review" in item for item in errors))

    def test_html_report_requires_browser_verification(self) -> None:
        plan = self.make_execute()
        plan["evidence"]["presentation"]["browser_verification"] = "not-applicable"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("HTML report requires" in item for item in errors))

    def test_full_campaign_cannot_disable_core_delivery(self) -> None:
        plan = self.make_execute()
        plan["execution"]["scope"] = "full-campaign"
        presentation = plan["evidence"]["presentation"]
        presentation["html_report"] = "not-requested"
        presentation["sequence_visibility"] = "not-requested"
        presentation["structure_visuals"] = "preferred"
        presentation["browser_verification"] = "not-applicable"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("html_report to be required" in item for item in errors))
        self.assertTrue(any("sequence_visibility to be required" in item for item in errors))
        self.assertTrue(any("structure_visuals to be required" in item for item in errors))

    def test_manual_handoff_is_a_valid_bound_route(self) -> None:
        plan = self.make_execute()
        stage = plan["execution"]["stages"][0]
        stage["route_kind"] = "manual-handoff"
        stage["provider"] = "reviewed-companion-runner"
        errors, _ = MODULE.validate(plan)
        self.assertFalse(any("route_kind must be one of" in item for item in errors), errors)

    def test_unconstrained_discovery_must_be_locked_before_execution(self) -> None:
        plan = self.make_execute()
        plan["target"]["site"]["mode"] = "unconstrained-discovery"
        plan["target"]["site"]["residues"] = []
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("custom-campaign" in item for item in errors))

        plan["execution"]["scope"] = "custom-campaign"
        errors, warnings = MODULE.validate(plan)
        self.assertFalse(any("unconstrained-discovery" in item for item in errors), errors)
        self.assertTrue(any("site-discovery" in item for item in warnings))

    def test_explicit_stage_ids_separate_identity_from_repeated_roles(self) -> None:
        plan = self.make_execute()
        first = plan["execution"]["stages"][0]
        first["stage_id"] = "prediction-fast"
        second = dict(first)
        second["stage_id"] = "prediction-full"
        plan["execution"]["stages"].append(second)
        errors, _ = MODULE.validate(plan)
        self.assertFalse(any("stage IDs must be unique" in item for item in errors), errors)

        second["stage_id"] = "prediction-fast"
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("stage IDs must be unique" in item for item in errors))

    def test_artifact_budget_is_explicit_and_bounded(self) -> None:
        plan = self.make_execute()
        plan["execution"]["artifact_budget"] = {
            "max_output_files_per_overlay": 256,
            "max_output_bytes_per_overlay": 640 * 1024 * 1024,
            "max_output_bytes_per_artifact": 512 * 1024 * 1024,
        }
        errors, _ = MODULE.validate(plan)
        self.assertFalse(any("artifact_budget" in item for item in errors), errors)

        plan["execution"]["artifact_budget"]["max_output_files_per_overlay"] = 5000
        errors, _ = MODULE.validate(plan)
        self.assertTrue(any("max_output_files_per_overlay" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
