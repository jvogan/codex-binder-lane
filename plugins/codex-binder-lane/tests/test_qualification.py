from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "codex-binder-lane" / "scripts" / "validate_qualification.py"
PROFILES = ROOT / "skills" / "codex-binder-lane" / "assets" / "profiles"
SPEC = importlib.util.spec_from_file_location("validate_qualification", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class QualificationLedgerTests(unittest.TestCase):
    def load(self, name: str) -> dict[str, object]:
        return json.loads((PROFILES / name).read_text(encoding="utf-8"))

    def execute_ledger(self, *, state: str, claim: str) -> dict[str, object]:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        ledger.update({"claim_ceiling": claim, "mode": "execute", "unpriced_work": []})
        state_index = MODULE.EVIDENCE_STATES.index(state)
        for stage in ledger["stages"]:
            stage["evidence_history"] = list(MODULE.EVIDENCE_STATES[: state_index + 1])
            stage["evidence_state"] = state
            stage["route_kind"] = "local"
            stage["provider"] = "local-fixture"
            stage["egress_class"] = "local-only"
            stage["artifact_validation"] = state == "artifact-validated"
            for name in ("adapter", "capability", "source", "model", "weights", "runtime"):
                stage[name] = {"id": f"{name}-fixture", "revision": "v1"}
            for license_kind in ("code", "weights", "service"):
                stage["licenses"][license_kind] = {
                    "commercial_allowed": True,
                    "license_id": "Apache-2.0",
                    "redistribution_allowed": True,
                    "source": f"license:{license_kind}-fixture-v1",
                }
            stage["price"] = {
                "confidence": "high",
                "estimate_usd": 0,
                "source": "pricing:fixture-v1",
            }
        return ledger

    def test_offline_plan_only_profiles_validate(self) -> None:
        for name in (
            "classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json",
            "complexa-codesign-independent-holo-apo-validation.plan.json",
        ):
            with self.subTest(name=name):
                self.assertEqual(MODULE.validate(self.load(name)), [])

    def test_skipped_evidence_state_fails_closed(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        stage = ledger["stages"][0]
        stage["evidence_history"] = ["catalogued", "bound"]
        stage["evidence_state"] = "bound"
        errors = MODULE.validate(ledger)
        self.assertTrue(any("may not skip" in item for item in errors))

    def test_private_remote_egress_requires_authorization(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        ledger["data_classification"] = "private"
        stage = ledger["stages"][0]
        stage.update({"route_kind": "fal", "provider": "provider-unselected", "egress_class": "remote-external"})
        errors = MODULE.validate(ledger)
        self.assertTrue(any("private_data_authorized" in item for item in errors))

    def test_preflight_requires_license_and_price_facts(self) -> None:
        ledger = self.load("complexa-codesign-independent-holo-apo-validation.plan.json")
        stage = ledger["stages"][0]
        stage["evidence_history"] = ["catalogued", "visible", "bound", "preflight-passed"]
        stage["evidence_state"] = "preflight-passed"
        errors = MODULE.validate(ledger)
        self.assertTrue(any("licenses.code.license_id" in item for item in errors))
        self.assertTrue(any("preflight requires price" in item for item in errors))

    def test_live_unpriced_work_provider_confusion_and_secret_are_rejected(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        ledger["mode"] = "execute"
        ledger["claim_ceiling"] = "computational-candidate"
        stage = ledger["stages"][0]
        stage.update(
            {
                "route_kind": "modal",
                "provider": "modal",
                "egress_class": "remote-external",
            }
        )
        stage["_".join(("api", "key"))] = "forbidden"
        errors = MODULE.validate(ledger)
        self.assertTrue(any("retains unpriced" in item for item in errors))
        self.assertTrue(any("provider must identify" in item for item in errors))
        self.assertTrue(any("credential" in item for item in errors))

    def test_plan_only_profile_cannot_assert_readiness_or_claim_escalation(self) -> None:
        ledger = copy.deepcopy(self.load("complexa-codesign-independent-holo-apo-validation.plan.json"))
        ledger["claim_ceiling"] = "transport-proven"
        ledger["ready"] = True
        errors = MODULE.validate(ledger)
        self.assertTrue(any("plan mode" in item for item in errors))
        self.assertTrue(any("readiness" in item for item in errors))

    def test_execute_rejects_catalogued_unbound_stages(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        ledger.update({"mode": "execute", "unpriced_work": []})
        errors = MODULE.validate(ledger)
        self.assertTrue(any("execute mode requires preflight-passed" in item for item in errors))

    def test_transport_claim_requires_executed_stage_evidence(self) -> None:
        ledger = self.execute_ledger(state="preflight-passed", claim="transport-proven")
        errors = MODULE.validate(ledger)
        self.assertTrue(any("transport-proven requires executed" in item for item in errors))

    def test_computational_candidate_requires_artifact_validated_stages(self) -> None:
        ledger = self.execute_ledger(state="executed", claim="computational-candidate")
        errors = MODULE.validate(ledger)
        self.assertTrue(any("computational-candidate requires artifact-validated" in item for item in errors))

        validated = self.execute_ledger(state="artifact-validated", claim="computational-candidate")
        self.assertEqual(MODULE.validate(validated), [])

    def test_cross_model_claim_fails_without_independent_family_evidence(self) -> None:
        ledger = self.execute_ledger(state="artifact-validated", claim="cross-model-supported")
        errors = MODULE.validate(ledger)
        self.assertTrue(any("independent model-family evidence" in item for item in errors))

    def test_unknown_claim_is_unavailable_under_this_schema(self) -> None:
        ledger = self.execute_ledger(state="artifact-validated", claim="unsupported-claim")
        errors = MODULE.validate(ledger)
        self.assertIn("claim_ceiling is invalid", errors)

    def test_executed_evidence_requires_execute_mode(self) -> None:
        ledger = self.execute_ledger(state="executed", claim="plan-only")
        ledger["mode"] = "dry-run"
        errors = MODULE.validate(ledger)
        self.assertTrue(any("executed evidence requires mode=execute" in item for item in errors))

    def test_exact_root_and_nested_key_sets_reject_extensions(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        ledger["operator_note"] = "untracked metadata"
        ledger["stages"][0]["provider_metadata"] = {"region": "local"}
        ledger["stages"][0]["price"]["currency"] = "USD"
        ledger["stages"][0]["licenses"]["code"]["notice"] = "extra"
        errors = MODULE.validate(ledger)
        self.assertTrue(any("ledger contains unsupported keys" in item for item in errors))
        self.assertTrue(any("stages[0] contains unsupported keys" in item for item in errors))
        self.assertTrue(any("stages[0].price contains unsupported keys" in item for item in errors))
        self.assertTrue(any("licenses.code contains unsupported keys" in item for item in errors))

    def test_required_root_and_nested_keys_reject_omissions(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        del ledger["unpriced_work"]
        stage = ledger["stages"][0]
        del stage["runtime"]
        del stage["model"]["revision"]
        del stage["licenses"]["service"]
        del stage["price"]["confidence"]
        errors = MODULE.validate(ledger)
        self.assertTrue(any("ledger is missing required keys: unpriced_work" in item for item in errors))
        self.assertTrue(any("stages[0] is missing required keys: runtime" in item for item in errors))
        self.assertTrue(any("stages[0].model is missing required keys: revision" in item for item in errors))
        self.assertTrue(any("stages[0].licenses is missing required keys: service" in item for item in errors))
        self.assertTrue(any("stages[0].price is missing required keys: confidence" in item for item in errors))

    def test_portable_identifiers_and_artifact_types_reject_paths_and_duplicates(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        ledger["campaign_id"] = "../campaign"
        stage = ledger["stages"][0]
        stage["stage_id"] = "generation/site"
        stage["input_artifact_types"] = ["locked-target-structure", "locked-target-structure"]
        stage["output_artifact_types"] = ["candidate coordinates"]
        errors = MODULE.validate(ledger)
        self.assertTrue(any("campaign_id must be a portable slug" in item for item in errors))
        self.assertTrue(any("stage_id must be a portable slug" in item for item in errors))
        self.assertTrue(any("must not repeat artifact types" in item for item in errors))
        self.assertTrue(any("unsafe artifact type" in item for item in errors))

    def test_source_references_reject_urls_private_hosts_and_credential_strings(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        stage = ledger["stages"][0]
        credential_key = "_".join(("api", "key"))
        private_host = ".".join(("10", "0", "0", "7"))
        stage["price"]["source"] = (
            "https://pricing.example.invalid?" + credential_key + "=plaintext"
        )
        stage["licenses"]["code"]["source"] = f"https://{private_host}/license"
        ledger["unpriced_work"] = ["Bearer abcdefghijklmnopqrstuvwxyz"]
        errors = MODULE.validate(ledger)
        self.assertTrue(any("price.source must be a safe source reference" in item for item in errors))
        self.assertTrue(any("licenses.code.source must be a safe source reference" in item for item in errors))
        self.assertTrue(any("credential-bearing URL" in item for item in errors))
        self.assertTrue(any("private host: 10.0.0.7" in item for item in errors))
        self.assertTrue(any("credential-like string" in item for item in errors))

    def test_safe_source_references_accept_closed_forms(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        stage = ledger["stages"][0]
        stage["price"]["source"] = "pricing:provider-price-sheet-v1"
        stage["licenses"]["code"]["source"] = "license:code-license-v1"
        errors = MODULE.validate(ledger)
        self.assertFalse(any("safe source reference" in item for item in errors))

    def test_manual_handoff_is_a_bound_remote_route(self) -> None:
        ledger = self.load("classic-rfdiffusion-proteinmpnn-independent-prediction.plan.json")
        stage = ledger["stages"][0]
        stage["route_kind"] = "manual-handoff"
        stage["provider"] = "reviewed-companion-runner"
        stage["egress_class"] = "remote-external"
        errors = MODULE.validate(ledger)
        self.assertFalse(any("route_kind is invalid" in item for item in errors), errors)

    def test_cli_uses_plain_text_by_default_and_json_when_requested(self) -> None:
        ledger = self.load("complexa-codesign-independent-holo-apo-validation.plan.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            plain = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            structured = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
            ledger["campaign_id"] = "invalid/id"
            path.write_text(json.dumps(ledger), encoding="utf-8")
            failed_plain = subprocess.run(
                [sys.executable, str(SCRIPT), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            failed_structured = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(plain.returncode, 0)
        self.assertTrue(plain.stdout.startswith("Qualification ledger is valid:"))
        self.assertEqual(structured.returncode, 0)
        self.assertEqual(json.loads(structured.stdout), {"errors": [], "ok": True})
        self.assertEqual(failed_plain.returncode, 1)
        self.assertIn("ERROR: campaign_id must be a portable slug", failed_plain.stdout)
        self.assertEqual(failed_structured.returncode, 1)
        self.assertFalse(json.loads(failed_structured.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
