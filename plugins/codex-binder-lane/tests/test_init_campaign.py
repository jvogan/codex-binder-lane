from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "codex-binder-lane" / "scripts" / "init_campaign.py"
QUALIFICATION_VALIDATOR = (
    ROOT / "skills" / "codex-binder-lane" / "scripts" / "validate_qualification.py"
)
EXPECTED_FILES = {
    "codex-binder-plan.json",
    "qualification-ledger.json",
    "residue-map.template.csv",
    "target-site-lock.template.json",
}


class InitCampaignTests(unittest.TestCase):
    def run_cli(
        self,
        campaign_id: str,
        output: Path,
        *,
        profile: str = "classic",
        confidentiality: str = "public",
        as_json: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            "--profile",
            profile,
            "--confidentiality",
            confidentiality,
        ]
        if as_json:
            command.append("--json")
        command.extend(("--", campaign_id, str(output)))
        return subprocess.run(command, check=False, capture_output=True, text=True)

    def test_classic_initialization_is_campaign_specific_and_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = self.run_cli(
                "public-receptor-pilot",
                output,
                profile="classic",
                confidentiality="private",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads(result.stdout)
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["status"], "initialized-plan-only")
            self.assertEqual(summary["campaign_id"], "public-receptor-pilot")
            self.assertEqual(summary["profile"], "classic")
            self.assertEqual(summary["confidentiality"], "private")
            self.assertFalse(summary["dispatch_eligible"])
            self.assertFalse(summary["network_or_provider_calls"])
            self.assertEqual(
                {item["path"] for item in summary["files"]}, EXPECTED_FILES
            )
            self.assertEqual({path.name for path in output.iterdir()}, EXPECTED_FILES)

            for item in summary["files"]:
                payload = (output / item["path"]).read_bytes()
                self.assertEqual(item["size_bytes"], len(payload))
                self.assertEqual(item["sha256"], hashlib.sha256(payload).hexdigest())

            plan = json.loads((output / "codex-binder-plan.json").read_text())
            self.assertEqual(plan["campaign_id"], "public-receptor-pilot")
            self.assertEqual(plan["mode"], "plan")
            self.assertEqual(plan["target"]["confidentiality"], "private")
            self.assertEqual(
                plan["target"]["target_lock"]["path"],
                "target-site-lock.template.json",
            )
            self.assertIsNone(plan["target"]["target_lock"]["sha256"])
            self.assertEqual(plan["execution"]["stages"], [])
            self.assertFalse(plan["authorization"]["private_data_authorized"])
            self.assertEqual(plan["evidence"]["claim_ceiling"], "plan-only")

            qualification = json.loads(
                (output / "qualification-ledger.json").read_text()
            )
            self.assertEqual(qualification["campaign_id"], "public-receptor-pilot")
            self.assertEqual(qualification["data_classification"], "private")
            self.assertEqual(qualification["mode"], "plan")
            self.assertFalse(qualification["private_data_authorized"])
            self.assertEqual(
                qualification["stages"][0]["stage_id"], "backbone-generation"
            )
            self.assertTrue(
                all(
                    stage["route_kind"] == "unbound"
                    for stage in qualification["stages"]
                )
            )
            validation = subprocess.run(
                [
                    sys.executable,
                    str(QUALIFICATION_VALIDATOR),
                    str(output / "qualification-ledger.json"),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                validation.returncode, 0, validation.stdout + validation.stderr
            )
            self.assertEqual(json.loads(validation.stdout), {"errors": [], "ok": True})

            target_lock = json.loads(
                (output / "target-site-lock.template.json").read_text()
            )
            self.assertEqual(target_lock["campaign_id"], "public-receptor-pilot")
            self.assertEqual(target_lock["confidentiality"], "private")
            self.assertEqual(target_lock["claim_ceiling"], "plan-only")
            self.assertEqual(
                target_lock["residue_map"]["path"], "residue-map.template.csv"
            )
            self.assertIsNone(target_lock["target_id"])

            header = (output / "residue-map.template.csv").read_text().splitlines()
            self.assertEqual(len(header), 1)
            self.assertEqual(
                header[0],
                "source_chain_id,author_residue_number,insertion_code,"
                "campaign_chain_id,campaign_residue_number,residue_name,meaning",
            )

    def test_complexa_profile_is_selected_without_binding_a_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = self.run_cli(
                "complexa-comparison",
                output,
                profile="complexa",
                confidentiality="restricted",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ledger = json.loads((output / "qualification-ledger.json").read_text())
            self.assertEqual(ledger["data_classification"], "restricted")
            self.assertEqual(ledger["stages"][0]["stage_id"], "codesign")
            self.assertEqual(ledger["stages"][0]["evidence_state"], "catalogued")
            self.assertTrue(
                all(stage["provider"] is None for stage in ledger["stages"])
            )

    def test_equal_inputs_produce_byte_identical_starters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = [root / "first", root / "second"]
            for output in outputs:
                result = self.run_cli("deterministic-starter", output)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            first = {path.name: path.read_bytes() for path in outputs[0].iterdir()}
            second = {path.name: path.read_bytes() for path in outputs[1].iterdir()}
            self.assertEqual(first, second)

    def test_existing_and_symlink_outputs_are_refused_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            sentinel = existing / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            result = self.run_cli("existing-output", existing)
            self.assertEqual(result.returncode, 1)
            self.assertIn("already exists", json.loads(result.stdout)["errors"][0])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

            outside = root / "outside"
            outside.mkdir()
            linked = root / "linked"
            linked.symlink_to(outside, target_is_directory=True)
            linked_result = self.run_cli("linked-output", linked)
            self.assertEqual(linked_result.returncode, 1)
            self.assertIn(
                "already exists", json.loads(linked_result.stdout)["errors"][0]
            )
            self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_output_parent_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            result = self.run_cli("linked-parent", linked_parent / "campaign")
            self.assertEqual(result.returncode, 1)
            self.assertTrue(
                any(
                    "non-symlink" in error
                    for error in json.loads(result.stdout)["errors"]
                )
            )
            self.assertEqual(list(real_parent.iterdir()), [])

    def test_unsafe_campaign_ids_are_refused_before_output_creation(self) -> None:
        unsafe_ids = (
            "../escape",
            "UPPERCASE",
            "contains/slash",
            "contains space",
            "-leading",
            "trailing-",
            "two--hyphens",
            "x" * 129,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, campaign_id in enumerate(unsafe_ids):
                with self.subTest(campaign_id=campaign_id):
                    output = root / f"campaign-{index}"
                    result = self.run_cli(campaign_id, output)
                    self.assertEqual(result.returncode, 1)
                    payload = json.loads(result.stdout)
                    self.assertFalse(payload["ok"])
                    self.assertTrue(
                        any("portable slug" in item for item in payload["errors"])
                    )
                    self.assertFalse(output.exists())

    def test_human_summary_states_the_offline_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            result = self.run_cli("human-summary", output, as_json=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Initialized plan-only Binder Lane campaign", result.stdout)
            self.assertIn("No network or provider calls were made", result.stdout)
            self.assertIn("Dispatch remains disabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
