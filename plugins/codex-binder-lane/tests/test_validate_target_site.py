from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "codex-binder-lane" / "scripts" / "validate_target_site.py"
SPEC = importlib.util.spec_from_file_location("validate_target_site", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TargetSiteLockValidationTests(unittest.TestCase):
    def make_valid(self, root: Path) -> dict:
        source = b"ORIGINAL SOURCE BYTES\n"
        normalized = b"data_SYNTHETIC_NORMALIZED\n"
        residue_map = (
            b"source_chain_id,author_residue_number,insertion_code,"
            b"campaign_chain_id,campaign_residue_number\n"
            b"A,42,,T,1\n"
            b"A,42,A,T,2\n"
        )
        (root / "inputs").mkdir(parents=True, exist_ok=True)
        (root / "maps").mkdir(exist_ok=True)
        (root / "inputs/normalized.cif").write_bytes(normalized)
        (root / "maps/residue-map.csv").write_bytes(residue_map)
        return {
            "schema_version": "codex-binder-target-site-lock/v1",
            "campaign_id": "campaign-001",
            "target_id": "target-001",
            "confidentiality": "public",
            "source_lock": {
                "source_id": "source-001",
                "source_version": "v1",
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "source_size_bytes": len(source),
                "input_sha256": hashlib.sha256(normalized).hexdigest(),
                "input_size_bytes": len(normalized),
            },
            "primary_input": {
                "path": "inputs/normalized.cif",
                "sha256": hashlib.sha256(normalized).hexdigest(),
                "size_bytes": len(normalized),
            },
            "chains": [
                {
                    "source_chain_id": "A",
                    "campaign_chain_id": "T",
                    "role": "target",
                },
                {
                    "source_chain_id": "B",
                    "campaign_chain_id": "C",
                    "role": "context",
                },
            ],
            "residue_map": {
                "path": "maps/residue-map.csv",
                "sha256": hashlib.sha256(residue_map).hexdigest(),
                "size_bytes": len(residue_map),
            },
            "site": {
                "site_id": "site-001",
                "mode": "explicit-residues",
                "numbering_scheme": (
                    "PDB author numbering mapped to contiguous campaign numbering"
                ),
                "residues": [
                    {
                        "campaign_chain_id": "T",
                        "campaign_residue_number": 1,
                        "author_residue_number": "42",
                        "insertion_code": None,
                    },
                    {
                        "campaign_chain_id": "T",
                        "campaign_residue_number": 2,
                        "author_residue_number": "42",
                        "insertion_code": "A",
                    },
                ],
                "evidence": "Residues copied from a reviewed synthetic fixture map.",
            },
            "claim_ceiling": "transport-proven",
        }

    def write_residue_map(self, root: Path, lock: dict, data: bytes) -> None:
        (root / lock["residue_map"]["path"]).write_bytes(data)
        lock["residue_map"]["sha256"] = hashlib.sha256(data).hexdigest()
        lock["residue_map"]["size_bytes"] = len(data)

    def run_cli(
        self, lock: Path, artifact_root: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPT), str(lock), "--json"]
        if artifact_root is not None:
            command.extend(["--artifact-root", str(artifact_root)])
        return subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_valid_lock_and_cli_pass_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            self.assertEqual(MODULE.validate(lock, root), [])
            (root / "locks").mkdir()
            lock_path = root / "locks/target-site.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            result = self.run_cli(lock_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {"errors": [], "ok": True})
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_explicit_artifact_root_resolves_refs_outside_lock_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            metadata = root / "metadata"
            metadata.mkdir()
            lock_path = metadata / "target-site.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            result = self.run_cli(lock_path, root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {"errors": [], "ok": True})

    def test_exact_hash_and_byte_locks_are_required_and_cross_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            lock["source_lock"]["source_sha256"] = "A" * 64
            lock["source_lock"]["source_size_bytes"] = True
            lock["source_lock"]["input_size_bytes"] += 1
            lock["primary_input"]["sha256"] = "0" * 64
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("source_sha256" in item for item in errors))
            self.assertTrue(any("source_size_bytes" in item for item in errors))
            self.assertTrue(any("exactly match" in item for item in errors))
            self.assertTrue(any("SHA-256 mismatch" in item for item in errors))

    def test_rejects_absolute_traversal_and_backslash_artifact_paths(self) -> None:
        for unsafe in (
            Path("/").joinpath("tmp", "input.cif").as_posix(),
            "../input.cif",
            "inputs\\normalized.cif",
            "inputs/./normalized.cif",
            "inputs//normalized.cif",
            "inputs/normalized.cif/",
            "inputs/normalized.cif\n",
        ):
            with self.subTest(path=unsafe), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                lock = self.make_valid(root)
                lock["primary_input"]["path"] = unsafe
                errors = MODULE.validate(lock, root)
                self.assertTrue(any("safe relative POSIX path" in item for item in errors))

    def test_rejects_symlinked_lock_artifact_and_artifact_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            outside = root / "outside.cif"
            outside.write_bytes((root / "inputs/normalized.cif").read_bytes())
            (root / "inputs/normalized.cif").unlink()
            (root / "inputs/normalized.cif").symlink_to(outside)
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("symlinked artifact paths" in item for item in errors))

            lock_path = root / "real-lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            lock_link = root / "lock-link.json"
            lock_link.symlink_to(lock_path)
            result = self.run_cli(lock_link)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertTrue(any("symlink" in item for item in json.loads(result.stdout)["errors"]))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            real_maps = root / "real-maps"
            (root / "maps").rename(real_maps)
            (root / "maps").symlink_to(real_maps, target_is_directory=True)
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("symlinked artifact paths" in item for item in errors))

    def test_rejects_unknown_fields_and_malformed_types_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            lock["unexpected"] = "value"
            lock["source_lock"]["unexpected"] = "value"
            lock["site"]["residues"][0]["unexpected"] = "value"
            errors = MODULE.validate(lock, root)
            self.assertGreaterEqual(sum("unknown fields" in item for item in errors), 3)

            malformed = copy.deepcopy(lock)
            malformed["source_lock"] = []
            malformed["chains"] = {}
            malformed["site"] = "not-an-object"
            malformed["primary_input"] = []
            errors = MODULE.validate(malformed, root)
            self.assertTrue(errors)

    def test_rejects_duplicate_or_ambiguous_chain_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            lock["chains"][1]["source_chain_id"] = "A"
            lock["chains"][1]["campaign_chain_id"] = "T"
            lock["chains"][0]["role"] = "context"
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("source_chain_id values must be unique" in item for item in errors))
            self.assertTrue(any("campaign_chain_id values must be unique" in item for item in errors))
            self.assertTrue(any("role=target" in item for item in errors))

    def test_rejects_duplicate_residues_and_invalid_insertion_code_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            duplicate = copy.deepcopy(lock["site"]["residues"][0])
            lock["site"]["residues"].append(duplicate)
            lock["site"]["residues"][1]["author_residue_number"] = "42A"
            lock["site"]["residues"][1]["insertion_code"] = ""
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("duplicate campaign residue" in item for item in errors))
            self.assertTrue(any("without an insertion code" in item for item in errors))
            self.assertTrue(any("uppercase alphanumeric" in item for item in errors))

    def test_rejects_resealed_map_that_omits_an_exact_site_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            residue_map = (
                b"source_chain_id,author_residue_number,insertion_code,"
                b"campaign_chain_id,campaign_residue_number\n"
                b"A,999,,T,1\n"
                b"A,42,A,T,2\n"
            )
            self.write_residue_map(root, lock, residue_map)
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("site.residues[0] has no exact residue_map row" in item for item in errors))

    def test_residue_map_header_is_exact_and_unambiguous(self) -> None:
        cases = (
            (
                b"source_chain_id,author_residue_number,insertion_code,campaign_chain_id\n"
                b"A,42,,T\n",
                "missing required fields",
            ),
            (
                b"source_chain_id,author_residue_number,insertion_code,"
                b"campaign_chain_id,campaign_residue_number,extra\n"
                b"A,42,,T,1,value\n",
                "1 unknown field",
            ),
            (
                b"source_chain_id,author_residue_number,insertion_code,"
                b"campaign_chain_id,campaign_residue_number,campaign_residue_number\n"
                b"A,42,,T,1,1\n",
                "duplicate fields",
            ),
        )
        for residue_map, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                lock = self.make_valid(root)
                self.write_residue_map(root, lock, residue_map)
                errors = MODULE.validate(lock, root)
                self.assertTrue(any(expected in item for item in errors), errors)

    def test_residue_map_rejects_invalid_encoding_controls_and_malformed_rows(self) -> None:
        header = (
            b"source_chain_id,author_residue_number,insertion_code,"
            b"campaign_chain_id,campaign_residue_number\n"
        )
        cases = (
            (header + b"A,42,,T,1\xff\n", "valid UTF-8 CSV"),
            (header + b"A,42,,T,\x001\n", "control character"),
            (header + b"A,42,,T\n", "exactly 5 fields"),
            (header + b"\n", "mapping values"),
            (header + b'A,"42,,T,1\n', "well-formed CSV"),
        )
        for residue_map, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                lock = self.make_valid(root)
                self.write_residue_map(root, lock, residue_map)
                errors = MODULE.validate(lock, root)
                self.assertTrue(any(expected in item for item in errors), errors)

    def test_residue_map_rejects_undeclared_chain_pairs_and_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            residue_map = (
                b"source_chain_id,author_residue_number,insertion_code,"
                b"campaign_chain_id,campaign_residue_number\n"
                b"A,42,,T,1\n"
                b"A,42,A,T,2\n"
                b"B,50,,T,3\n"
                b"A,43,,T,1\n"
                b"A,42,,T,4\n"
            )
            self.write_residue_map(root, lock, residue_map)
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("chain pair" in item for item in errors), errors)
            self.assertTrue(any("duplicates a campaign residue" in item for item in errors), errors)
            self.assertTrue(any("duplicates an author residue" in item for item in errors), errors)

    def test_oversized_locked_artifact_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            residue_map_path = root / lock["residue_map"]["path"]
            with residue_map_path.open("wb") as handle:
                handle.truncate(MODULE.MAX_RESIDUE_MAP_BYTES + 1)
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("artifact exceeds" in item for item in errors), errors)

    def test_site_residues_must_map_to_target_chains_with_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            lock["site"]["residues"][0]["campaign_chain_id"] = "C"
            lock["site"]["numbering_scheme"] = "unknown"
            lock["site"]["evidence"] = "TBD"
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("role=target" in item for item in errors))
            self.assertTrue(any("numbering_scheme" in item for item in errors))
            self.assertTrue(any("site.evidence" in item for item in errors))

    def test_confidentiality_and_claim_locks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            del lock["claim_ceiling"]
            lock["confidentiality"] = "unresolved"
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("missing required fields" in item for item in errors))
            self.assertTrue(any("confidentiality" in item for item in errors))

            lock = self.make_valid(root)
            lock["claim_ceiling"] = "cross-model-supported"
            errors = MODULE.validate(lock, root)
            self.assertTrue(any("may only be plan-only or transport-proven" in item for item in errors))

    def test_rejects_credentials_and_private_endpoints_in_retained_text(self) -> None:
        separator = "/"
        http_prefix = "https:" + (separator * 2)
        credential_key = "_".join(("api", "key"))
        home_path = "~" + separator + separator.join(("private", "target.cif"))
        cases = (
            (
                credential_key + "=" + "sk-" + "concrete-secret-value",
                "credential material",
            ),
            (
                "Source: " + http_prefix + "local" + "host:8443/target",
                "private or local endpoint",
            ),
            (
                "Source: file:"
                + (separator * 3)
                + separator.join(("Users", "example", "private", "target.cif")),
                "local file URL",
            ),
            (
                "Source: "
                + http_prefix
                + "example.org/target?"
                + ("to" + "ken")
                + "="
                + ("sec" + "ret"),
                "credential-bearing URL",
            ),
            (
                "Source: " + http_prefix + "name:" + "secret@example.org/target",
                "credential-bearing URL",
            ),
            (
                "Source: " + http_prefix + "[" + "::1]" + separator + "target",
                "private or local endpoint",
            ),
            (
                "Source: s3:"
                + (separator * 2)
                + "private-bucket"
                + separator
                + "target.cif",
                "non-HTTP URI",
            ),
            (
                "Source: ssh:"
                + (separator * 2)
                + ".".join(("10", "0", "0", "7"))
                + separator
                + "target.cif",
                "non-HTTP URI",
            ),
            (
                "Path: "
                + Path("/").joinpath("Users", "example", "private", "target.cif").as_posix(),
                "absolute POSIX path",
            ),
            (
                "Path: C:"
                + "\\"
                + "\\".join(("Users", "example", "private", "target.cif")),
                "absolute Windows path",
            ),
            ("Path: " + home_path, "home-relative path"),
        )
        for evidence, expected in cases:
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                lock = self.make_valid(root)
                lock["site"]["evidence"] = evidence
                errors = MODULE.validate(lock, root)
                self.assertTrue(any(expected in item for item in errors), errors)
                self.assertNotIn(evidence, "\n".join(errors))

    def test_public_http_provenance_remains_portable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = self.make_valid(root)
            lock["site"]["evidence"] = "Reviewed source: https://example.org/records/1ZVH."
            self.assertEqual(MODULE.validate(lock, root), [])

    def test_malformed_json_and_non_object_root_are_structured_cli_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed = root / "malformed.json"
            malformed.write_text("{not-json", encoding="utf-8")
            result = self.run_cli(malformed)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])

            array = root / "array.json"
            array.write_text("[]", encoding="utf-8")
            result = self.run_cli(array)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertTrue(any("must be an object" in item for item in json.loads(result.stdout)["errors"]))


if __name__ == "__main__":
    unittest.main()
