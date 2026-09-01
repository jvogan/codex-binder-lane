from __future__ import annotations

import hashlib
import importlib.util
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
SPEC = importlib.util.spec_from_file_location("campaign_overlay", OVERLAY)
assert SPEC and SPEC.loader
OVERLAY_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERLAY_MODULE)


class CampaignOverlayTests(unittest.TestCase):
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
                    "adapter": {"id": "fixture-adapter", "revision": "v1"},
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
                    "source": {"id": plan_stage["capability"], "revision": "v1"},
                    "stage_id": plan_stage.get("stage_id", plan_stage["role"]),
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

    def build_base_packet(
        self,
        root: Path,
        *,
        remote: bool = False,
        qualification_mode: str = "execute",
    ) -> tuple[Path, dict[str, object]]:
        bundle = root / "fixture"
        result = self.run_command(BUILDER, bundle, "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan_path = bundle / "codex-binder-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if remote:
            stage = plan["execution"]["stages"][0]
            stage.update(
                {
                    "estimated_cost_usd": 0.01,
                    "paid": True,
                    "provider": "fal-serverless",
                    "route_kind": "fal",
                }
            )
            plan["authorization"]["paid_compute_authorized"] = True
            plan["budget"]["estimate_usd"] = 0.01
            plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        qualification = self.qualification_for(plan)
        qualification["mode"] = qualification_mode
        qualification_path = root / "qualification.json"
        qualification_path.write_text(
            json.dumps(qualification, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        packet = root / "packet"
        result = self.run_command(
            PACKET,
            "materialize",
            plan_path,
            bundle / "locks/target-site.json",
            qualification_path,
            packet,
            "--artifact-root",
            bundle,
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["dispatch_eligible"])
        return packet, plan

    def companion_receipt(
        self,
        root: Path,
        packet: Path,
        plan: dict[str, object],
        *,
        execution_state: str = "completed",
        claim_ceiling: str = "transport-proven",
        provider_request_id: str | None = None,
    ) -> tuple[Path, Path, dict[str, object]]:
        manifest_bytes = (packet / "campaign/packet-manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        by_path = {entry["path"]: entry for entry in manifest["files"]}
        stage = plan["execution"]["stages"][0]
        output_root = root / "companion-output"
        output_path = output_root / "artifacts/stage-output.json"
        output_path.parent.mkdir(parents=True)
        output_bytes = b'{"fixture":"companion-stage-output"}\n'
        output_path.write_bytes(output_bytes)
        outputs = []
        if execution_state == "completed":
            outputs = [
                {
                    "path": "artifacts/stage-output.json",
                    "sha256": hashlib.sha256(output_bytes).hexdigest(),
                    "size_bytes": len(output_bytes),
                }
            ]
        receipt = {
            "schema_version": "codex-binder-companion-stage-receipt/v1",
            "receipt_id": "fixture-receipt-001",
            "campaign_id": plan["campaign_id"],
            "base_packet_id": manifest["packet_id"],
            "base_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "stage_id": stage.get("stage_id", stage["role"]),
            "capability": {"id": stage["capability"], "revision": "v1"},
            "route_kind": stage["route_kind"],
            "provider": stage["provider"],
            "execution_state": execution_state,
            "provider_request_id": provider_request_id,
            "inputs": [by_path[plan["target"]["structure_or_sequence"]],
            ],
            "outputs": outputs,
            "cost": {
                "status": "observed",
                "estimate_usd": stage["estimated_cost_usd"],
                "observed_usd": stage["estimated_cost_usd"],
            },
            "cleanup_state": (
                "verified"
                if stage["route_kind"] in OVERLAY_MODULE.validate_qualification.REMOTE_ROUTE_KINDS
                else "not-applicable"
            ),
            "claim_ceiling": claim_ceiling,
        }
        receipt_path = root / "receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return receipt_path, output_root, receipt

    def files(self, root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def import_overlay(
        self, packet: Path, receipt: Path, output: Path, artifact_root: Path
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            OVERLAY,
            "import-stage",
            packet,
            receipt,
            output,
            "--artifact-root",
            artifact_root,
            "--json",
        )

    def test_import_is_deterministic_and_keeps_base_packet_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            before = self.files(packet)
            receipt, output_root, _ = self.companion_receipt(root, packet, plan)
            overlays = [root / "overlay-a", root / "overlay-b"]
            for overlay in overlays:
                result = self.import_overlay(packet, receipt, overlay, output_root)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertFalse(payload["dispatch_attempted"])
                self.assertFalse(payload["network_used_by_importer"])
                self.assertFalse(payload["provider_execution_verified_by_importer"])
                self.assertEqual(payload["claim_ceiling"], "transport-proven")
            self.assertEqual(self.files(overlays[0]), self.files(overlays[1]))
            self.assertEqual(before, self.files(packet))
            base_status = json.loads((packet / "campaign/status.json").read_text(encoding="utf-8"))
            overlay_status = json.loads((overlays[0] / "overlay-status.json").read_text(encoding="utf-8"))
            self.assertEqual(base_status["claim_ceiling"], "plan-only")
            self.assertFalse(base_status["dispatch_eligible"])
            self.assertEqual(overlay_status["claim_ceiling"], "transport-proven")
            self.assertEqual(overlay_status["base_packet_claim_ceiling"], "plan-only")

            verify = self.run_command(OVERLAY, "verify", packet, overlays[0], "--json")
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["overlay_valid"])

    def test_imports_completed_remote_receipt_with_retained_fal_request_id_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root, remote=True)
            receipt, output_root, _ = self.companion_receipt(
                root,
                packet,
                plan,
                provider_request_id=(
                    "esmfold2-rfdiffusion3-006-proteinmpnn-00-identity-r1-"
                    "seed-0002-c8729dc7a353"
                ),
            )
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt, overlay, output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["claim_ceiling"], "transport-proven")
            verify = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_rejects_completed_receipt_with_nonterminal_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root, remote=True)
            receipt_path, output_root, receipt = self.companion_receipt(
                root,
                packet,
                plan,
                provider_request_id="fixture-remote-request-001",
            )
            receipt["cleanup_state"] = "pending"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = self.import_overlay(packet, receipt_path, root / "overlay", output_root)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(
                any(
                    "terminal cleanup_state" in error
                    for error in json.loads(result.stdout)["errors"]
                )
            )

    def test_accepts_not_applicable_cleanup_for_completed_managed_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root, remote=True)
            receipt_path, output_root, receipt = self.companion_receipt(
                root,
                packet,
                plan,
                provider_request_id="fixture-managed-request-001",
            )
            self.assertEqual(receipt["route_kind"], "fal")
            receipt["cleanup_state"] = "not-applicable"
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = self.import_overlay(packet, receipt_path, root / "overlay", output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_strict_receipt_json_rejects_non_finite_number(self) -> None:
        with self.assertRaises(OVERLAY_MODULE.OverlayError):
            OVERLAY_MODULE.parse_strict_json_object(b'{"value": NaN}', "fixture")

    def test_rejects_completed_receipt_when_qualification_remains_plan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root, qualification_mode="plan")
            receipt_path, output_root, _ = self.companion_receipt(root, packet, plan)
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertTrue(
                any(
                    "qualification mode to be execute" in error
                    for error in json.loads(result.stdout)["errors"]
                )
            )

    def test_rejects_output_nested_in_base_packet_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            before = self.files(packet)
            receipt, output_root, _ = self.companion_receipt(root, packet, plan)
            overlay = packet / "nested-overlay"
            result = self.import_overlay(packet, receipt, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertEqual(before, self.files(packet))
            status = self.run_command(PACKET, "status", packet, "--json")
            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)

    def test_rejects_duplicate_json_keys_before_retaining_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, _ = self.companion_receipt(root, packet, plan)
            receipt_text = receipt_path.read_text(encoding="utf-8")
            duplicate_secret = "sk-" + "not-retainable-secret"
            receipt_text = receipt_text.replace(
                '"provider_request_id": null,',
                f'"provider_request_id": "{duplicate_secret}",\n'
                '  "provider_request_id": null,',
            )
            receipt_path.write_text(receipt_text, encoding="utf-8")
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertTrue(
                any("duplicate JSON key" in error for error in json.loads(result.stdout)["errors"])
            )

    def test_rejects_casefolded_output_aliases_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            alias = dict(receipt["outputs"][0])
            alias["path"] = "artifacts/STAGE-OUTPUT.json"
            receipt["outputs"] = sorted([alias, receipt["outputs"][0]], key=lambda item: item["path"])
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertTrue(
                any("case-folding" in error for error in json.loads(result.stdout)["errors"])
            )

    def test_rejects_casefolded_output_prefix_collisions_before_file_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            template = receipt["outputs"][0]
            receipt["outputs"] = [
                {**template, "path": "artifacts/Foo"},
                {**template, "path": "artifacts/foo/bar"},
            ]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertTrue(
                any(
                    "normalization and case-folding" in error
                    for error in json.loads(result.stdout)["errors"]
                )
            )

    def test_rejects_windows_reserved_output_paths_before_file_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            cases = [
                "CON.json",
                "CONIN$",
                "CONOUT$",
                "COM¹",
                "COM².txt",
                "LPT³",
                "CON .txt",
                "foo:bar",
            ]
            for index, component in enumerate(cases):
                with self.subTest(component=component):
                    receipt["outputs"][0]["path"] = f"artifacts/{component}"
                    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                    overlay = root / f"overlay-{index}"
                    result = self.import_overlay(
                        packet, receipt_path, overlay, output_root
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(overlay.exists())
                    self.assertTrue(
                        any(
                            "portable cross-platform components" in error
                            for error in json.loads(result.stdout)["errors"]
                        )
                    )

    def test_rejects_sensitive_url_in_text_output_before_retention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            output_path = output_root / receipt["outputs"][0]["path"]
            output_bytes = (
                b'{"download":"https://files.example.org/result?'
                + b"sig="
                + b"SECRET"
                + b'-SIGNATURE"}\n'
            )
            output_path.write_bytes(output_bytes)
            receipt["outputs"][0].update(
                {
                    "sha256": hashlib.sha256(output_bytes).hexdigest(),
                    "size_bytes": len(output_bytes),
                }
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertTrue(
                any(
                    "sensitive text rejected" in error
                    for error in json.loads(result.stdout)["errors"]
                )
            )

    def test_rejects_delimited_credentials_and_non_http_private_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            output_reference = receipt["outputs"][0]
            output_reference["path"] = "artifacts/stage-output.txt"
            output_path = output_root / output_reference["path"]
            cases = {
                "equals-url": (
                    ".txt",
                    "api" + "_key=https://files.example.org/opaque" + "credential123456\n"
                ),
                "colon-value": (".txt", "to" + "ken=abc:defghijklmnopqrstuvwxyz\n"),
                "toml": (
                    ".txt",
                    "api" + '_key = "https://files.example.org/opaque' + 'credential123456"\n',
                ),
                "grpc-private": (
                    ".txt",
                    "endpoint=grpc://service." + "internal:443\n",
                ),
                "fal-text": (
                    ".txt",
                    "fal" + "_key=abcdefghijklmnopqrstuvwx\n",
                ),
                "fal-json": (
                    ".json",
                    '{"fal' + '_key":"abcdefghijklmnopqrstuvwx"}\n',
                ),
            }
            for label, (suffix, text_payload) in cases.items():
                with self.subTest(label=label):
                    output_reference["path"] = f"artifacts/stage-output{suffix}"
                    output_path = output_root / output_reference["path"]
                    output_bytes = text_payload.encode("utf-8")
                    output_path.write_bytes(output_bytes)
                    output_reference.update(
                        {
                            "sha256": hashlib.sha256(output_bytes).hexdigest(),
                            "size_bytes": len(output_bytes),
                        }
                    )
                    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                    overlay = root / f"overlay-{label}"
                    result = self.import_overlay(
                        packet, receipt_path, overlay, output_root
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertFalse(overlay.exists())
                    self.assertTrue(
                        any(
                            "sensitive text rejected" in error
                            for error in json.loads(result.stdout)["errors"]
                        )
                    )

    def test_verify_fails_closed_on_unreadable_undeclared_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, _ = self.companion_receipt(root, packet, plan)
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            undeclared = overlay / "undeclared"
            undeclared.mkdir()
            (undeclared / "secret.txt").write_text("not declared\n", encoding="utf-8")
            undeclared.chmod(0)
            try:
                verify = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            finally:
                undeclared.chmod(0o700)
            self.assertEqual(verify.returncode, 1)
            self.assertTrue(
                any(
                    "tree traversal failed" in error
                    for error in json.loads(verify.stdout)["errors"]
                )
            )

    def test_verify_rejects_self_consistent_overlay_with_sensitive_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, _, receipt = self.companion_receipt(root, packet, plan)
            output_path = receipt["outputs"][0]["path"]
            output_bytes = (
                b'{"download":"https://files.example.org/result?'
                + b"sig="
                + b"SECRET"
                + b'-SIGNATURE"}\n'
            )
            receipt["outputs"][0].update(
                {
                    "sha256": hashlib.sha256(output_bytes).hexdigest(),
                    "size_bytes": len(output_bytes),
                }
            )
            receipt_bytes = (json.dumps(receipt, sort_keys=True) + "\n").encode("utf-8")
            receipt_path.write_bytes(receipt_bytes)
            base = OVERLAY_MODULE.load_base_packet(packet)
            payloads, overlay_id = OVERLAY_MODULE.build_overlay_payloads(
                base,
                receipt_bytes,
                receipt,
                {output_path: output_bytes},
            )
            manifest_bytes = OVERLAY_MODULE.build_manifest(
                base, receipt, payloads, overlay_id
            )
            overlay = root / "forged-overlay"
            for relative_path, data in payloads.items():
                destination = overlay / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            (overlay / OVERLAY_MODULE.MANIFEST_PATH).write_bytes(manifest_bytes)
            (overlay / OVERLAY_MODULE.MANIFEST_SHA_PATH).write_text(
                f"{hashlib.sha256(manifest_bytes).hexdigest()}  overlay-manifest.json\n",
                encoding="ascii",
            )
            verify = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            self.assertEqual(verify.returncode, 1)
            self.assertTrue(
                any(
                    "sensitive text rejected" in error
                    for error in json.loads(verify.stdout)["errors"]
                )
            )

    def test_preflights_declared_output_count_and_bytes_before_file_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            template = receipt["outputs"][0]
            receipt["outputs"] = [
                {**template, "path": f"artifacts/missing-{index:02d}.json"}
                for index in range(31)
            ]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(packet, receipt_path, root / "overlay-count", output_root)
            self.assertEqual(result.returncode, 1)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("at most 30 entries before path validation" in error for error in errors))

            receipt["outputs"] = [
                {
                    **template,
                    "path": f"artifacts/oversized-{index}.bin",
                    "size_bytes": 512 * 1024 * 1024,
                }
                for index in range(2)
            ]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(packet, receipt_path, root / "overlay-bytes", output_root)
            self.assertEqual(result.returncode, 1)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("aggregate limit before artifact reads" in error for error in errors))

    def test_frozen_plan_can_raise_per_overlay_output_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "fixture"
            result = self.run_command(BUILDER, bundle, "--json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan_path = bundle / "codex-binder-plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["execution"]["artifact_budget"] = {
                "max_output_files_per_overlay": 64,
                "max_output_bytes_per_overlay": 1024 * 1024,
                "max_output_bytes_per_artifact": 512 * 1024,
            }
            plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            qualification_path = root / "qualification.json"
            qualification_path.write_text(
                json.dumps(self.qualification_for(plan), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            packet = root / "packet"
            result = self.run_command(
                PACKET,
                "materialize",
                plan_path,
                bundle / "locks/target-site.json",
                qualification_path,
                packet,
                "--artifact-root",
                bundle,
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            template = receipt["outputs"][0]
            receipt["outputs"] = [
                {**template, "path": f"artifacts/missing-{index:02d}.json"}
                for index in range(31)
            ]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(packet, receipt_path, root / "overlay", output_root)
            self.assertEqual(result.returncode, 1)
            errors = json.loads(result.stdout)["errors"]
            self.assertFalse(any("at most 30 entries" in error for error in errors), errors)
            self.assertTrue(any("cannot inspect" in error for error in errors), errors)

    def test_paid_cost_must_bind_estimate_but_truthful_overage_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root, remote=True)
            receipt_path, output_root, receipt = self.companion_receipt(
                root,
                packet,
                plan,
                provider_request_id="req_123",
            )
            receipt["cost"] = {
                "status": "not-applicable",
                "estimate_usd": None,
                "observed_usd": None,
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(packet, receipt_path, root / "overlay-na", output_root)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(
                any("paid stages" in error for error in json.loads(result.stdout)["errors"])
            )

            receipt["cost"] = {
                "status": "estimated",
                "estimate_usd": 0,
                "observed_usd": None,
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(
                packet, receipt_path, root / "overlay-drift", output_root
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(
                any("frozen plan" in error for error in json.loads(result.stdout)["errors"])
            )

            receipt["cost"] = {
                "status": "observed",
                "estimate_usd": 0.01,
                "observed_usd": 0.02,
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            overlay = root / "overlay-overage"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            status = json.loads((overlay / "overlay-status.json").read_text(encoding="utf-8"))
            self.assertTrue(status["observed_cost_over_campaign_ceiling"])
            self.assertEqual(status["cost_observed_usd_reported"], 0.02)

    def test_rejects_wrong_base_binding_without_partial_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            receipt["base_packet_id"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt_path, overlay, output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(overlay.exists())
            self.assertTrue(
                any("base_packet_id" in error for error in json.loads(result.stdout)["errors"])
            )

    def test_rejects_failed_receipts_that_claim_outputs_or_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            receipt["execution_state"] = "failed"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(packet, receipt_path, root / "overlay", output_root)
            self.assertEqual(result.returncode, 1)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("failed receipts" in error for error in errors))

    def test_imports_a_hash_bound_failed_stage_without_escalating_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt, output_root, _ = self.companion_receipt(
                root,
                packet,
                plan,
                execution_state="failed",
                claim_ceiling="plan-only",
            )
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt, overlay, output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["execution_state"], "failed")
            self.assertEqual(payload["claim_ceiling"], "plan-only")
            self.assertEqual(payload["output_count"], 0)
            self.assertFalse((overlay / "artifacts").exists())
            verify = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_rejects_secret_or_private_endpoints_in_a_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt_path, output_root, receipt = self.companion_receipt(root, packet, plan)
            receipt["provider_request_id"] = "https://service." + "internal/job"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = self.import_overlay(packet, receipt_path, root / "overlay", output_root)
            self.assertEqual(result.returncode, 1)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("private host" in error for error in errors))

    def test_verify_rejects_tampered_overlay_or_base_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt, output_root, _ = self.companion_receipt(root, packet, plan)
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt, overlay, output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (overlay / "artifacts/stage-output.json").write_text("changed\n", encoding="utf-8")
            verify = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            self.assertEqual(verify.returncode, 1)
            self.assertTrue(any("hash" in error for error in json.loads(verify.stdout)["errors"]))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt, output_root, _ = self.companion_receipt(root, packet, plan)
            overlay = root / "overlay"
            result = self.import_overlay(packet, receipt, overlay, output_root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            (packet / "campaign/report.md").write_text("changed\n", encoding="utf-8")
            verify = self.run_command(OVERLAY, "verify", packet, overlay, "--json")
            self.assertEqual(verify.returncode, 1)
            self.assertTrue(any("packet payload" in error for error in json.loads(verify.stdout)["errors"]))

    def test_rejects_symlinked_companion_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, plan = self.build_base_packet(root)
            receipt, output_root, _ = self.companion_receipt(root, packet, plan)
            output = output_root / "artifacts/stage-output.json"
            target = root / "outside.json"
            target.write_bytes(output.read_bytes())
            output.unlink()
            output.symlink_to(target)
            result = self.import_overlay(packet, receipt, root / "overlay", output_root)
            self.assertEqual(result.returncode, 1)
            self.assertFalse((root / "overlay").exists())
            self.assertTrue(any("symlink" in error for error in json.loads(result.stdout)["errors"]))


if __name__ == "__main__":
    unittest.main()
