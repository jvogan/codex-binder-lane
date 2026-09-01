from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "codex-binder-lane" / "scripts"
BUILD = SCRIPT_DIR / "build_fixture_bundle.py"
VALIDATE = SCRIPT_DIR / "validate_bundle.py"
VALIDATE_PLAN = SCRIPT_DIR / "validate_plan.py"
VALIDATE_TARGET = SCRIPT_DIR / "validate_target_site.py"


class FixtureBundleTests(unittest.TestCase):
    def run_script(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def reseal_payload(self, bundle: Path, relative_path: str, data: bytes) -> None:
        (bundle / relative_path).write_bytes(data)
        manifest_path = bundle / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = next(item for item in manifest["files"] if item["path"] == relative_path)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        entry["size_bytes"] = len(data)
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)
        (bundle / "bundle-manifest.sha256").write_text(
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  bundle-manifest.json\n",
            encoding="ascii",
        )

    def mutate_json_and_reseal(self, bundle: Path, relative_path: str, mutate: object) -> None:
        path = bundle / relative_path
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)  # type: ignore[operator]
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.reseal_payload(bundle, relative_path, data)

    def test_build_is_deterministic_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            for destination in (first, second):
                run = self.run_script(BUILD, str(destination), "--json")
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                build_summary = json.loads(run.stdout)
                self.assertTrue(build_summary["ok"])
                self.assertEqual(build_summary["file_count"], 29)

            self.assertEqual(
                (first / "bundle-manifest.json").read_bytes(),
                (second / "bundle-manifest.json").read_bytes(),
            )
            self.assertEqual(
                (first / "bundle-manifest.sha256").read_bytes(),
                (second / "bundle-manifest.sha256").read_bytes(),
            )
            first_files = {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second).as_posix(): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)
            self.assertEqual(len(first_files), 29)

            validation = self.run_script(VALIDATE, str(first), "--json")
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
            self.assertEqual(json.loads(validation.stdout), {"errors": [], "ok": True})

            plan_validation = self.run_script(
                VALIDATE_PLAN, str(first / "codex-binder-plan.json"), "--json"
            )
            self.assertEqual(plan_validation.returncode, 0, plan_validation.stdout + plan_validation.stderr)
            self.assertEqual(json.loads(plan_validation.stdout)["errors"], [])

            target_validation = self.run_script(
                VALIDATE_TARGET, str(first / "locks/target-site.json"), "--json"
            )
            self.assertEqual(
                target_validation.returncode,
                0,
                target_validation.stdout + target_validation.stderr,
            )
            self.assertEqual(json.loads(target_validation.stdout), {"errors": [], "ok": True})

            metrics = json.loads((first / "metrics/metrics.json").read_text(encoding="utf-8"))
            self.assertIsNone(metrics["records"][0]["scientific_score"])
            self.assertIsNone(metrics["records"][0]["scientific_confidence"])
            self.assertEqual(metrics["records"][0]["ranking_status"], "unranked")
            self.assertEqual(
                (first / "sequences/synthetic-placeholder.fasta").read_text(encoding="ascii").splitlines()[1],
                "XXXX",
            )

    def test_payload_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            build = self.run_script(BUILD, str(bundle), "--json")
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            pdb = bundle / "structures/synthetic-placeholder.pdb"
            pdb.write_bytes(pdb.read_bytes() + b"REMARK TAMPERED\n")

            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            errors = json.loads(validation.stdout)["errors"]
            self.assertTrue(any("hash mismatch: structures/synthetic-placeholder.pdb" in item for item in errors))

    def test_missing_payload_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            build = self.run_script(BUILD, str(bundle), "--json")
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            (bundle / "sequences/synthetic-placeholder.fasta").unlink()

            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertNotIn("Traceback", validation.stderr)
            payload = json.loads(validation.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(any("synthetic-placeholder.fasta" in item for item in payload["errors"]))

    def test_malformed_manifest_path_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            build = self.run_script(BUILD, str(bundle), "--json")
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            manifest_path = bundle / "bundle-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][0]["path"] = ["not-a-path"]
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertNotIn("Traceback", validation.stderr)
            payload = json.loads(validation.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(any("path must be a string" in item for item in payload["errors"]))

    def test_symlinked_payload_returns_structured_error_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            bundle = base / "bundle"
            outside = base / "outside.fasta"
            build = self.run_script(BUILD, str(bundle), "--json")
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            outside.write_bytes(b">SYN-CANARY-001 non-biological software sentinel\nXXXX\n")
            payload = bundle / "sequences/synthetic-placeholder.fasta"
            payload.unlink()
            payload.symlink_to(outside)

            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertNotIn("Traceback", validation.stderr)
            result = json.loads(validation.stdout)
            self.assertFalse(result["ok"])
            self.assertTrue(any("symlink" in item for item in result["errors"]))

    def test_rejects_impossible_execution_state_and_unverified_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.assertEqual(self.run_script(BUILD, str(bundle), "--json").returncode, 0)

            def mutate(value: dict[str, object]) -> None:
                value["execution_state"] = {
                    "packet": "emitted",
                    "runtime": "unprobed",
                    "invocation": "completed",
                    "output_validation": "passed",
                }
                value["output_artifacts"] = value["coordinate_artifacts"]

            self.mutate_json_and_reseal(bundle, "viewer/structure-handoff.json", mutate)
            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            errors = json.loads(validation.stdout)["errors"]
            self.assertTrue(any("unprobed or unavailable runtime cannot be invoked" in item for item in errors))

    def test_non_array_outputs_return_structured_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.assertEqual(self.run_script(BUILD, str(bundle), "--json").returncode, 0)
            self.mutate_json_and_reseal(
                bundle,
                "media/pymol-handoff.json",
                lambda value: value.__setitem__("output_artifacts", "not-an-array"),
            )
            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertNotIn("Traceback", validation.stderr)
            self.assertTrue(
                any("output_artifacts must be an array" in item for item in json.loads(validation.stdout)["errors"])
            )

    def test_malformed_metric_identifier_returns_structured_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.assertEqual(self.run_script(BUILD, str(bundle), "--json").returncode, 0)

            def mutate(value: dict[str, object]) -> None:
                value["definitions"][0]["metric_id"] = []  # type: ignore[index]

            self.mutate_json_and_reseal(bundle, "metrics/metrics.json", mutate)
            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertNotIn("Traceback", validation.stderr)
            self.assertTrue(any("definitions" in item for item in json.loads(validation.stdout)["errors"]))

    def test_receipt_dependencies_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.assertEqual(self.run_script(BUILD, str(bundle), "--json").returncode, 0)
            self.mutate_json_and_reseal(
                bundle,
                "receipts/02-handoffs.json",
                lambda value: value.__setitem__("inputs", []),
            )
            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertTrue(
                any("required inputs dependencies are missing" in item for item in json.loads(validation.stdout)["errors"])
            )

    def test_handoff_classification_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.assertEqual(self.run_script(BUILD, str(bundle), "--json").returncode, 0)
            self.mutate_json_and_reseal(
                bundle,
                "media/chimerax-handoff.json",
                lambda value: value.__setitem__("claim_ceiling", "plan-only"),
            )
            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertTrue(any("claim ceiling mismatch" in item for item in json.loads(validation.stdout)["errors"]))

    def test_report_claim_ceiling_and_handoff_state_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            self.assertEqual(self.run_script(BUILD, str(bundle), "--json").returncode, 0)
            report_path = bundle / "report/report.md"
            tampered = report_path.read_bytes() + b"\nClaim ceiling: `transport-proven`\n"
            self.reseal_payload(bundle, "report/report.md", tampered)
            validation = self.run_script(VALIDATE, str(bundle), "--json")
            self.assertNotEqual(validation.returncode, 0)
            self.assertTrue(
                any("claim ceiling statement must appear exactly once" in item for item in json.loads(validation.stdout)["errors"])
            )


if __name__ == "__main__":
    unittest.main()
