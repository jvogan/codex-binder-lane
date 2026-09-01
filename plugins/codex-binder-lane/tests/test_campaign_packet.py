from __future__ import annotations

import json
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "codex-binder-lane" / "scripts"
BUILDER = SCRIPTS / "build_fixture_bundle.py"
PACKET = SCRIPTS / "campaign_packet.py"
SPEC = importlib.util.spec_from_file_location("campaign_packet", PACKET)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CampaignPacketTests(unittest.TestCase):
    def run_command(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PACKET), *[str(value) for value in arguments]],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def build_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        bundle = root / "fixture"
        result = subprocess.run(
            [sys.executable, str(BUILDER), str(bundle), "--json"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan_path = bundle / "codex-binder-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        qualification = self.qualification_for(plan)
        qualification_path = root / "qualification.json"
        qualification_path.write_text(
            json.dumps(qualification, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return plan_path, bundle / "locks/target-site.json", qualification_path

    def qualification_for(self, plan: dict[str, object]) -> dict[str, object]:
        stages = []
        for plan_stage in plan["execution"]["stages"]:
            stage_id = plan_stage.get("stage_id", plan_stage["role"])
            capability_id = plan_stage["capability"]
            stages.append(
                {
                    "adapter": {"id": "fixture-adapter", "revision": "v1"},
                    "artifact_validation": False,
                    "capability": {"id": capability_id, "revision": "v1"},
                    "egress_class": "local-only",
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
                    "model": {"id": "fixture-model", "revision": "v1"},
                    "output_artifact_types": ["sealed-stage-output"],
                    "price": {
                        "confidence": "high",
                        "estimate_usd": plan_stage["estimated_cost_usd"],
                        "source": "pricing:fixture-zero-v1",
                    },
                    "provider": plan_stage["provider"],
                    "route_kind": plan_stage["route_kind"],
                    "runtime": {"id": "python", "revision": "v1"},
                    "source": {"id": capability_id, "revision": "v1"},
                    "stage_id": stage_id,
                    "weights": {"id": "fixture-weights", "revision": "v1"},
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

    def reseal_target(
        self,
        plan_path: Path,
        target_path: Path,
        mutate,
    ) -> None:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        target = json.loads(target_path.read_text(encoding="utf-8"))
        mutate(plan, target)
        target_bytes = (
            json.dumps(target, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        target_path.write_bytes(target_bytes)
        plan["target"]["target_lock"] = {
            "path": "locks/target-site.json",
            "sha256": hashlib.sha256(target_bytes).hexdigest(),
            "size_bytes": len(target_bytes),
        }
        plan_path.write_text(
            json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def packet_files(self, packet: Path) -> dict[str, bytes]:
        return {
            path.relative_to(packet).as_posix(): path.read_bytes()
            for path in packet.rglob("*")
            if path.is_file()
        }

    def test_materialize_status_and_resume_check_stay_offline_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            materialized = json.loads(result.stdout)
            self.assertFalse(materialized["dispatch_eligible"])
            self.assertEqual(materialized["claim_ceiling"], "plan-only")
            self.assertRegex(materialized["packet_id"], r"^[0-9a-f]{64}$")
            self.assertTrue(any("evidence references" in item for item in materialized["blockers"]))
            status_record = json.loads(
                (packet / "campaign/status.json").read_text(encoding="utf-8")
            )
            self.assertTrue(status_record["qualification_declarations_complete"])
            self.assertNotIn("qualification_contract_complete", status_record)

            status = self.run_command("status", packet, "--json")
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
            status_payload = json.loads(status.stdout)
            self.assertTrue(status_payload["packet_valid"])
            self.assertFalse(status_payload["dispatch_eligible"])

            before = self.packet_files(packet)
            resume = self.run_command("resume-check", packet, "--json")
            self.assertEqual(resume.returncode, 2, resume.stdout + resume.stderr)
            self.assertFalse(json.loads(resume.stdout)["dispatch_attempted"])
            self.assertEqual(before, self.packet_files(packet))

    def test_materialization_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            packets = [root / "packet-a", root / "packet-b"]
            for packet in packets:
                result = self.run_command(
                    "materialize",
                    plan,
                    target,
                    qualification,
                    packet,
                    "--artifact-root",
                    target.parents[1],
                    "--json",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(self.packet_files(packets[0]), self.packet_files(packets[1]))

    def test_explicit_stage_ids_allow_repeated_scientific_roles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, target, _ = self.build_fixture(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            stages = plan["execution"]["stages"]
            stages[0]["role"] = "prediction"
            stages[0]["stage_id"] = "prediction-fast"
            stages[1]["role"] = "prediction"
            stages[1]["stage_id"] = "prediction-full"
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            qualification_path = root / "qualification-explicit-ids.json"
            qualification_path.write_text(
                json.dumps(self.qualification_for(plan), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan_path,
                target,
                qualification_path,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            graph = json.loads((packet / MODULE.GRAPH_PATH).read_text(encoding="utf-8"))
            self.assertEqual(
                [(stage["stage_id"], stage["role"]) for stage in graph["stages"]],
                [("prediction-fast", "prediction"), ("prediction-full", "prediction")],
            )

    def test_cross_contract_drift_is_rejected_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, target, qualification = self.build_fixture(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target"]["site"]["evidence"] = "A different site assertion."
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan_path,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(any("site evidence" in item for item in json.loads(result.stdout)["errors"]))
            self.assertFalse(packet.exists())

    def test_primary_target_path_drift_is_rejected_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan_path, target, qualification = self.build_fixture(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["target"]["structure_or_sequence"] = "structures/not-the-locked-input.cif"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan_path,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(
                any("primary target path" in item for item in json.loads(result.stdout)["errors"])
            )
            self.assertFalse(packet.exists())

    def test_noncanonical_and_prefix_colliding_paths_are_rejected(self) -> None:
        for value in (
            "structures/./input.cif",
            "structures//input.cif",
            "structures/input.cif/",
            "structures/input.cif\n",
        ):
            with self.subTest(value=value):
                self.assertFalse(MODULE.safe_relative_path(value))
        cases = (
            {"qualification", "qualification/qualification-ledger.json"},
            {"campaign", "campaign/status.json"},
            {"structures", "structures/residue-map.csv"},
        )
        for paths in cases:
            with self.subTest(paths=paths):
                self.assertIsNotNone(MODULE.prefix_collision(paths))

    def test_reserved_prefix_collision_is_rejected_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            bundle = target.parents[1]
            original = bundle / "structures/synthetic-placeholder.cif"
            collided = bundle / "qualification"
            original.rename(collided)

            def mutate(plan_value, target_value):
                plan_value["target"]["structure_or_sequence"] = "qualification"
                target_value["primary_input"]["path"] = "qualification"

            self.reseal_target(plan, target, mutate)
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                packet,
                "--artifact-root",
                bundle,
                "--json",
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertTrue(any("file and directory" in item for item in json.loads(result.stdout)["errors"]))
            self.assertFalse(packet.exists())

    def test_biological_intent_does_not_require_an_achieved_candidate_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)

            def mutate(plan_value, target_value):
                plan_value.pop("fixture", None)
                target_value.pop("fixture_kind", None)
                target_value.pop("non_biological", None)

            self.reseal_target(plan, target, mutate)
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            blockers = json.loads(result.stdout)["blockers"]
            self.assertFalse(any("computational-candidate" in item for item in blockers))
            self.assertTrue(any("evidence references" in item for item in blockers))

    def test_packet_resource_limits_fail_before_writes(self) -> None:
        too_many = {f"files/{index}.txt": b"" for index in range(MODULE.MAX_PACKET_FILES + 1)}
        with self.assertRaises(MODULE.PacketError):
            MODULE.validate_payload_budget(too_many)
        with mock.patch.object(MODULE, "MAX_PACKET_BYTES", 1):
            with self.assertRaises(MODULE.PacketError):
                MODULE.validate_payload_budget({"file.txt": b"12"})

    def test_tampering_and_undeclared_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            for mutation in ("tamper", "extra"):
                with self.subTest(mutation=mutation):
                    packet = root / f"packet-{mutation}"
                    result = self.run_command(
                        "materialize",
                        plan,
                        target,
                        qualification,
                        packet,
                        "--artifact-root",
                        target.parents[1],
                        "--json",
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if mutation == "tamper":
                        (packet / "campaign/status.json").write_text("{}\n", encoding="utf-8")
                    else:
                        (packet / "undeclared.txt").write_text("drift\n", encoding="utf-8")
                    status = self.run_command("status", packet, "--json")
                    self.assertEqual(status.returncode, 1)
                    self.assertNotIn("Traceback", status.stderr)

    def test_status_fails_closed_on_unreadable_undeclared_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            undeclared = packet / "undeclared"
            undeclared.mkdir()
            (undeclared / "secret.txt").write_text("not declared\n", encoding="utf-8")
            undeclared.chmod(0)
            try:
                status = self.run_command("status", packet, "--json")
            finally:
                undeclared.chmod(0o700)
            self.assertEqual(status.returncode, 1)
            self.assertTrue(
                any(
                    "tree traversal failed" in error
                    for error in json.loads(status.stdout)["errors"]
                )
            )

    def test_manifest_path_types_fail_with_a_specific_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            manifest_path = packet / MODULE.MANIFEST_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"][1]["path"] = 7
            manifest_bytes = MODULE.canonical_json_bytes(manifest)
            manifest_path.write_bytes(manifest_bytes)
            (packet / MODULE.MANIFEST_SHA_PATH).write_text(
                f"{MODULE.sha256_bytes(manifest_bytes)}  packet-manifest.json\n",
                encoding="ascii",
            )
            status = self.run_command("status", packet, "--json")
            self.assertEqual(status.returncode, 1)
            errors = json.loads(status.stdout)["errors"]
            self.assertTrue(any("path must be a string" in item for item in errors))
            self.assertFalse(any("TypeError" in item for item in errors))

    def test_existing_output_and_symlinked_output_parent_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            existing = root / "existing"
            existing.mkdir()
            existing_result = self.run_command(
                "materialize", plan, target, qualification, existing, "--json"
            )
            self.assertEqual(existing_result.returncode, 1)

            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(Path(outside), target_is_directory=True)
            linked_result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                linked_parent / "packet",
                "--json",
            )
            self.assertEqual(linked_result.returncode, 1)
            self.assertTrue(
                any("non-symlink" in item for item in json.loads(linked_result.stdout)["errors"])
            )
            self.assertFalse((Path(outside) / "packet").exists())

    def test_symlinked_output_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            outside_parent = Path(outside) / "parent"
            outside_parent.mkdir()
            alias = root / "alias"
            alias.symlink_to(Path(outside), target_is_directory=True)
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                alias / "parent/packet",
                "--json",
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(
                any("symlinked ancestor" in item for item in json.loads(result.stdout)["errors"])
            )
            self.assertFalse((outside_parent / "packet").exists())

    def test_packet_symlink_is_rejected_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            plan, target, qualification = self.build_fixture(root)
            packet = root / "packet"
            result = self.run_command(
                "materialize",
                plan,
                target,
                qualification,
                packet,
                "--artifact-root",
                target.parents[1],
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            campaign = packet / "campaign"
            moved = Path(outside) / "campaign"
            campaign.rename(moved)
            campaign.symlink_to(moved, target_is_directory=True)
            status = self.run_command("status", packet, "--json")
            self.assertEqual(status.returncode, 1)
            self.assertTrue(any("symlink" in item for item in json.loads(status.stdout)["errors"]))


if __name__ == "__main__":
    unittest.main()
