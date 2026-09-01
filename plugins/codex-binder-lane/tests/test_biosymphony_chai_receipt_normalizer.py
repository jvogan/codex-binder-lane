from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "codex-binder-lane" / "scripts"
BUILDER = SCRIPTS / "build_fixture_bundle.py"
PACKET = SCRIPTS / "campaign_packet.py"
OVERLAY = SCRIPTS / "campaign_overlay.py"
NORMALIZER = SCRIPTS / "normalize_biosymphony_chai_receipt.py"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BioSymphonyChaiReceiptNormalizerTests(unittest.TestCase):
    def run_command(self, script: Path, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *[str(value) for value in arguments]],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def qualification_for(self, plan: dict[str, object]) -> dict[str, object]:
        stages = []
        for plan_stage in plan["execution"]["stages"]:
            stages.append(
                {
                    "adapter": {"id": "biosymphony-chai-adapter", "revision": "v1"},
                    "artifact_validation": False,
                    "capability": {"id": plan_stage["capability"], "revision": "v1"},
                    "egress_class": (
                        "local-only"
                        if plan_stage["route_kind"] == "local"
                        else "remote-external"
                    ),
                    "evidence_history": [
                        "catalogued",
                        "visible",
                        "bound",
                        "preflight-passed",
                        "scientifically-qualified",
                    ],
                    "evidence_state": "scientifically-qualified",
                    "input_artifact_types": ["locked-target-input"],
                    "licenses": {
                        kind: {
                            "commercial_allowed": True,
                            "license_id": "Apache-2.0",
                            "redistribution_allowed": True,
                            "source": f"license:fixture-{kind}-v1",
                        }
                        for kind in ("code", "weights", "service")
                    },
                    "model": {"id": "chai-1", "revision": "v0.6.1"},
                    "output_artifact_types": ["complex-pdb", "pae", "metrics"],
                    "price": {
                        "confidence": "high",
                        "estimate_usd": plan_stage["estimated_cost_usd"],
                        "source": "pricing:fixture-fal-chai-v1",
                    },
                    "provider": plan_stage["provider"],
                    "route_kind": plan_stage["route_kind"],
                    "runtime": {"id": "fal-serverless", "revision": "v1"},
                    "source": {"id": plan_stage["capability"], "revision": "v1"},
                    "stage_id": plan_stage["role"],
                    "weights": {"id": "chai-1", "revision": "v0.6.1"},
                }
            )
        return {
            "campaign_id": plan["campaign_id"],
            "claim_ceiling": "plan-only",
            "data_classification": "public",
            "mode": "execute",
            "private_data_authorized": False,
            "schema_version": "codex-binder-qualification-ledger/v1",
            "stages": stages,
            "unpriced_work": [],
        }

    def artifact_ref(self, path: Path, relative_path: str) -> dict[str, object]:
        payload = path.read_bytes()
        return {
            "path": relative_path,
            "sha256": digest(payload),
            "size_bytes": len(payload),
        }

    def build_packet(self, root: Path, *, route_kind: str = "fal") -> tuple[Path, Path, dict[str, object]]:
        bundle = root / "fixture"
        result = self.run_command(BUILDER, bundle, "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan_path = bundle / "codex-binder-plan.json"
        target_path = bundle / "locks" / "target-site.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        stage = plan["execution"]["stages"][0]
        stage.update(
            {
                "capability": "biosymphony-chai-complex-prediction",
                "estimated_cost_usd": 0.01,
                "paid": True,
                "provider": "fal-serverless",
                "route_kind": route_kind,
            }
        )
        plan["authorization"]["paid_compute_authorized"] = True
        plan["budget"]["estimate_usd"] = 0.01
        plan["target"]["target_lock"] = self.artifact_ref(target_path, "locks/target-site.json")
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        qualification = self.qualification_for(plan)
        qualification_path = root / "qualification.json"
        qualification_path.write_text(
            json.dumps(qualification, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        packet = root / "packet"
        result = self.run_command(
            PACKET,
            "materialize",
            plan_path,
            target_path,
            qualification_path,
            packet,
            "--artifact-root",
            bundle,
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return packet, bundle, plan

    def create_native_stage(
        self, root: Path, bundle: Path, plan: dict[str, object]
    ) -> tuple[Path, Path, Path, str, int]:
        native_root = root / "native-stage"
        receipt_path = native_root / "chai/candidate-001/seed-0007/inference-receipt.json"
        raw_structure = native_root / "chai/candidate-001/seed-0007/run/complex.pdb"
        raw_pae = native_root / "chai/candidate-001/seed-0007/run/pae.json"
        complex_path = native_root / "predictions/candidate-001/seed-0007/complex.pdb"
        pae_path = native_root / "predictions/candidate-001/seed-0007/pae.json"
        metric_path = native_root / "predictions/candidate-001/seed-0007/measurement-source.json"
        identity_path = native_root / "predictions/candidate-001/seed-0007/runner-identity.json"
        for path in (
            receipt_path,
            raw_structure,
            raw_pae,
            complex_path,
            pae_path,
            metric_path,
            identity_path,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
        raw_structure.write_bytes(b"ATOM      1  CA  GLY A   1       0.0   0.0   0.0\nEND\n")
        raw_pae.write_bytes(b'{"pae":[[1.0]]}\n')
        complex_path.write_bytes(b"ATOM      1  CA  GLY A   1       1.0   1.0   1.0\nEND\n")
        pae_path.write_bytes(b'{"pae":[[2.0]],"plddt":[90.0]}\n')
        metric_path.write_bytes(b'{"interface_ipsae":0.42,"ok_rows":1}\n')
        identity_path.write_bytes(
            b'{"model_revision":"chai-1@v0.6.1","source_revision":"chai-lab@v0.6.1"}\n'
        )
        submitted_input = (bundle / plan["target"]["structure_or_sequence"]).read_bytes()
        request_id = "chai-candidate-001-seed-0007-0123456789ab"
        native_receipt = {
            "schema_version": 1,
            "ok": True,
            "runner_protocol": "fal",
            "fal_request_id": request_id,
            "input_fasta_sha256": digest(submitted_input),
            "structure_path": str(raw_structure),
            "structure_sha256": digest(raw_structure.read_bytes()),
            "pae_record": str(raw_pae),
        }
        receipt_path.write_text(
            json.dumps(native_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        observation = {
            "candidate_id": "candidate-001",
            "seed": 7,
            "status": "scored",
            "predictor": "chai",
            "runner_protocol": "fal",
            "fal_request_id": request_id,
            "inference_receipt_path": str(receipt_path),
            "inference_receipt_sha256": digest(receipt_path.read_bytes()),
            "fold_input_fasta_sha256": digest(submitted_input),
            "predicted_complex_path": str(complex_path),
            "predicted_complex_sha256": digest(complex_path.read_bytes()),
            "pae_path": str(pae_path),
            "pae_sha256": digest(pae_path.read_bytes()),
            "metric_source_path": str(metric_path),
            "metric_source_sha256": digest(metric_path.read_bytes()),
            "runner_identity_path": str(identity_path),
            "runner_identity_sha256": digest(identity_path.read_bytes()),
        }
        observations_path = native_root / "cofold-observations.jsonl"
        observations_path.write_text(json.dumps(observation, sort_keys=True) + "\n", encoding="utf-8")
        return native_root, receipt_path, observations_path, request_id, 7

    def normalize(
        self,
        packet: Path,
        native_root: Path,
        receipt_path: Path,
        observations_path: Path,
        output: Path,
        plan: dict[str, object],
        *,
        candidate_id: str = "candidate-001",
        seed: int = 7,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            NORMALIZER,
            "normalize-stage",
            packet,
            native_root,
            receipt_path,
            observations_path,
            output,
            "--stage-id",
            plan["execution"]["stages"][0]["role"],
            "--candidate-id",
            candidate_id,
            "--seed",
            seed,
            "--json",
        )

    def files(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def test_normalizes_and_imports_a_hash_bound_hosted_chai_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, bundle, plan = self.build_packet(root)
            native_root, receipt_path, observations_path, request_id, seed = self.create_native_stage(
                root, bundle, plan
            )
            normalized = root / "normalized"
            result = self.normalize(
                packet, native_root, receipt_path, observations_path, normalized, plan
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result_payload = json.loads(result.stdout)
            self.assertFalse(result_payload["network_used"])
            self.assertFalse(result_payload["dispatch_attempted"])
            self.assertFalse(result_payload["provider_execution_verified"])
            self.assertEqual(result_payload["artifact_count"], 4)

            receipt = json.loads((normalized / "companion-stage-receipt.json").read_text())
            self.assertEqual(receipt["schema_version"], "codex-binder-companion-stage-receipt/v1")
            self.assertEqual(receipt["provider_request_id"], request_id)
            self.assertEqual(receipt["cost"], {"status": "unknown", "estimate_usd": None, "observed_usd": None})
            self.assertEqual(receipt["cleanup_state"], "not-applicable")
            self.assertEqual(receipt["claim_ceiling"], "transport-proven")
            self.assertEqual(
                [item["path"] for item in receipt["outputs"]],
                sorted(item["path"] for item in receipt["outputs"]),
            )
            private_path_marker = "/" + "private" + "/"
            self.assertNotIn(private_path_marker, json.dumps(receipt, sort_keys=True))
            expected_prefix = f"artifacts/biosymphony-chai/candidate-001/seed-{seed:04d}/"
            self.assertTrue(all(item["path"].startswith(expected_prefix) for item in receipt["outputs"]))
            for item in receipt["outputs"]:
                payload = (normalized / item["path"]).read_bytes()
                self.assertEqual(item["sha256"], digest(payload))
                self.assertEqual(item["size_bytes"], len(payload))

            overlay = root / "overlay"
            imported = self.run_command(
                OVERLAY,
                "import-stage",
                packet,
                normalized / "companion-stage-receipt.json",
                overlay,
                "--artifact-root",
                normalized,
                "--json",
            )
            self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
            verified = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_equal_native_evidence_produces_equal_normalized_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, bundle, plan = self.build_packet(root)
            native_root, receipt_path, observations_path, _request_id, _seed = self.create_native_stage(
                root, bundle, plan
            )
            outputs = [root / "normalized-a", root / "normalized-b"]
            for output in outputs:
                result = self.normalize(
                    packet, native_root, receipt_path, observations_path, output, plan
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.files(outputs[0]), self.files(outputs[1]))

    def test_rejects_an_observation_that_does_not_hash_bind_the_native_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, bundle, plan = self.build_packet(root)
            native_root, receipt_path, observations_path, _request_id, _seed = self.create_native_stage(
                root, bundle, plan
            )
            observation = json.loads(observations_path.read_text())
            observation["inference_receipt_sha256"] = "0" * 64
            observations_path.write_text(json.dumps(observation) + "\n", encoding="utf-8")
            normalized = root / "normalized"
            result = self.normalize(
                packet, native_root, receipt_path, observations_path, normalized, plan
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(normalized.exists())
            self.assertIn("does not hash-bind", json.loads(result.stdout)["errors"][0])

    def test_rejects_a_non_fal_frozen_stage_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, bundle, plan = self.build_packet(root, route_kind="local")
            native_root, receipt_path, observations_path, _request_id, _seed = self.create_native_stage(
                root, bundle, plan
            )
            normalized = root / "normalized"
            result = self.normalize(
                packet, native_root, receipt_path, observations_path, normalized, plan
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(normalized.exists())
            self.assertIn("FAL route", json.loads(result.stdout)["errors"][0])

    def test_rejects_a_symlinked_native_artifact_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, bundle, plan = self.build_packet(root)
            native_root, receipt_path, observations_path, _request_id, _seed = self.create_native_stage(
                root, bundle, plan
            )
            observation = json.loads(observations_path.read_text())
            original = Path(observation["predicted_complex_path"])
            alias = original.with_name("complex-alias.pdb")
            alias.symlink_to(original)
            observation["predicted_complex_path"] = str(alias)
            observations_path.write_text(json.dumps(observation) + "\n", encoding="utf-8")
            normalized = root / "normalized"
            result = self.normalize(
                packet, native_root, receipt_path, observations_path, normalized, plan
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(normalized.exists())
            self.assertIn("symlinked paths are forbidden", json.loads(result.stdout)["errors"][0])


if __name__ == "__main__":
    unittest.main()
