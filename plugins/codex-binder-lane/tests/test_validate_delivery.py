from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "codex-binder-lane" / "scripts" / "validate_delivery.py"
SPEC = importlib.util.spec_from_file_location("validate_delivery", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeliveryValidationTests(unittest.TestCase):
    def png(self, width: int, height: int, rgb: tuple[int, int, int] = (255, 255, 255)) -> bytes:
        raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
        output = bytearray(b"\x89PNG\r\n\x1a\n")
        for chunk_type, payload in (
            (b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            (b"IDAT", zlib.compress(raw)),
            (b"IEND", b""),
        ):
            output.extend(struct.pack(">I", len(payload)))
            output.extend(chunk_type)
            output.extend(payload)
            output.extend(struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF))
        return bytes(output)

    def write(self, root: Path, relative: str, raw: bytes) -> dict[str, object]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }

    def mmcif(self, atoms: list[tuple[str, int]]) -> bytes:
        lines = [
            "data_fixture",
            "loop_",
            "_atom_site.group_PDB",
            "_atom_site.id",
            "_atom_site.type_symbol",
            "_atom_site.label_atom_id",
            "_atom_site.label_comp_id",
            "_atom_site.label_asym_id",
            "_atom_site.label_seq_id",
        ]
        for serial, (chain, residue) in enumerate(atoms, start=1):
            lines.append(f"ATOM {serial} C CA ALA {chain} {residue}")
        lines.append("#")
        return ("\n".join(lines) + "\n").encode()

    def pdb(self, atoms: list[tuple[str, int]]) -> bytes:
        lines = []
        for serial, (chain, residue) in enumerate(atoms, start=1):
            lines.append(
                f"ATOM  {serial:5d}  CA  ALA {chain:1s}{residue:4d}    "
                f"{float(serial):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C"
            )
        lines.extend(["TER", "END"])
        return ("\n".join(lines) + "\n").encode()

    def replace_coordinates(
        self,
        root: Path,
        index: dict,
        raw: bytes,
        suffix: str = ".cif",
    ) -> None:
        structure = index["candidates"][0]["structures"][0]
        coordinate_ref = structure["coordinates"]
        old_relative = str(coordinate_ref["path"])
        new_relative = str(Path(old_relative).with_suffix(suffix))
        if new_relative != old_relative:
            (root / old_relative).unlink()
            coordinate_ref["path"] = new_relative
            report_path = root / str(index["report"]["html"]["path"])
            report_raw = report_path.read_bytes().replace(
                old_relative.encode(), new_relative.encode()
            )
            report_path.write_bytes(report_raw)
            index["report"]["html"].update(
                {
                    "sha256": hashlib.sha256(report_raw).hexdigest(),
                    "size_bytes": len(report_raw),
                }
            )
        coordinate_path = root / new_relative
        coordinate_path.write_bytes(raw)
        coordinate_ref.update(
            {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        )

        recipe_ref = structure["visual_context"]["render_recipe"]
        recipe_path = root / str(recipe_ref["path"])
        recipe_payload = json.loads(recipe_path.read_bytes())
        recipe_payload["coordinates_sha256"] = coordinate_ref["sha256"]
        recipe_raw = (json.dumps(recipe_payload, separators=(",", ":")) + "\n").encode()
        recipe_path.write_bytes(recipe_raw)
        recipe_ref.update(
            {
                "sha256": hashlib.sha256(recipe_raw).hexdigest(),
                "size_bytes": len(recipe_raw),
            }
        )

    def replace_metric_value(self, root: Path, index: dict, value: object) -> None:
        structure = index["candidates"][0]["structures"][0]
        structure["site_metrics"][0]["value"] = value
        metrics_ref = structure["metrics"]
        metrics_path = root / str(metrics_ref["path"])
        metrics_payload = json.loads(metrics_path.read_bytes())
        metrics_payload["metrics"][0]["value"] = value
        metrics_raw = (json.dumps(metrics_payload, separators=(",", ":")) + "\n").encode()
        metrics_path.write_bytes(metrics_raw)
        metrics_ref.update(
            {
                "sha256": hashlib.sha256(metrics_raw).hexdigest(),
                "size_bytes": len(metrics_raw),
            }
        )
        report_ref = index["report"]["html"]
        report_path = root / str(report_ref["path"])
        report_raw = report_path.read_bytes().replace(b"0.75", str(value).encode())
        report_path.write_bytes(report_raw)
        report_ref.update(
            {"sha256": hashlib.sha256(report_raw).hexdigest(), "size_bytes": len(report_raw)}
        )

    def build_valid(self, root: Path) -> dict:
        candidate_id = "CAND-001"
        sequence = "ACDEFGHIKLMNPQRSTVWY"
        fasta = self.write(
            root, "sequences/CAND-001.fasta", f">{candidate_id}\n{sequence}\n".encode()
        )
        coordinates = self.write(
            root,
            "structures/CAND-001-fast.cif",
            self.mmcif([("T", 10), ("T", 12), ("B", 1)]),
        )
        target = self.write(
            root,
            "target/target.cif",
            self.mmcif([("T", 10), ("T", 12)]),
        )
        target_site_lock_raw = (
            '{"schema_version":"codex-binder-target-site-lock/v1",'
            '"campaign_id":"delivery-fixture","target_id":"TARGET-1",'
            '"primary_input":{"path":"target/target.cif","sha256":"'
            + str(target["sha256"])
            + '","size_bytes":'
            + str(target["size_bytes"])
            + '},"chains":[{"source_chain_id":"A","campaign_chain_id":"T","role":"target"}],'
            '"site":{"numbering_scheme":"campaign",'
            '"residues":[{"campaign_chain_id":"T","campaign_residue_number":10},'
            '{"campaign_chain_id":"T","campaign_residue_number":12}]}}\n'
        ).encode()
        target_site_lock = self.write(
            root,
            "target/target-site-lock.json",
            target_site_lock_raw,
        )
        plan_raw = (
            '{"schema_version":"codex-binder-lane/v1",'
            '"campaign_id":"delivery-fixture",'
            '"target":{"identifier":"TARGET-1","target_lock":{'
            '"path":"target/target-site-lock.json","sha256":"'
            + str(target_site_lock["sha256"])
            + '","size_bytes":'
            + str(target_site_lock["size_bytes"])
            + '}},"evidence":{"presentation":{'
            '"html_report":"required-by-user",'
            '"sequence_visibility":"required-by-user",'
            '"structure_visuals":"required-by-user",'
            '"video":"not-requested",'
            '"sequence_scope":"all-generated",'
            '"structure_scope":"all-predicted"}}}\n'
        ).encode()
        plan = self.write(root, "plan/codex-binder-plan.json", plan_raw)
        site_metrics = [
            {
                "metric_id": "hotspot-contact-fraction",
                "name": "Hotspot contact fraction",
                "value": 0.75,
                "unit": "fraction",
                "state": "measured",
                "source": "FAL Fast",
                "scope": "target-site",
            }
        ]
        metrics_raw = (
            '{"schema_version":"codex-binder-site-metrics/v1",'
            '"candidate_id":"CAND-001","render_id":"cand-001-fast",'
            '"metrics":[{"metric_id":"hotspot-contact-fraction",'
            '"name":"Hotspot contact fraction","value":0.75,"unit":"fraction",'
            '"state":"measured","source":"FAL Fast","scope":"target-site"}]}\n'
        ).encode()
        metrics = self.write(root, "metrics/CAND-001-fast.json", metrics_raw)
        render_raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#fff"/><circle cx="260" cy="300" r="170" fill="#9ecae1"/><circle cx="500" cy="300" r="95" fill="#f28e8e"/><circle cx="405" cy="300" r="24" fill="#f2c94c"/></svg>\n'
        render = self.write(
            root,
            "report/media/CAND-001-fast.svg",
            render_raw,
        )
        render_recipe_raw = (
            '{"schema_version":"codex-binder-render-recipe/v1",'
            '"candidate_id":"CAND-001","render_id":"cand-001-fast",'
            '"coordinates_sha256":"'
            + str(coordinates["sha256"])
            + '","render_sha256":"'
            + str(render["sha256"])
            + '","target_chains":["T"],"binder_chains":["B"],'
            '"site_residues":["T:10","T:12"],"background":"white",'
            '"renderer":"Structure Viewer","renderer_version":"fixture-1",'
            '"width":800,"height":600}\n'
        ).encode()
        render_recipe = self.write(
            root,
            "report/data/CAND-001-fast-render.json",
            render_recipe_raw,
        )
        screenshot = self.write(
            root,
            "report/browser/full-page.png",
            self.png(640, 480),
        )
        slash = chr(47)
        html_raw = f"""<!doctype html>
<html><body>
<section data-candidate-id="{candidate_id}">
  <code data-binder-sequence="{candidate_id}">{sequence}<{slash}code>
  <a data-sequence-download="{candidate_id}" href="../sequences/CAND-001.fasta">FASTA<{slash}a>
  <img data-structure-render="cand-001-fast" data-target-chains="T" data-binder-chains="B" data-target-site="T:10,T:12" data-site-highlighted="true" data-background="white" src="media/CAND-001-fast.svg" alt="CAND-001 bound to TARGET-1 at site T:10,T:12">
  <figcaption data-structure-caption="cand-001-fast">CAND-001 binder on TARGET-1 at locked site T:10 and T:12.</figcaption>
  <a data-structure-download="cand-001-fast" href="../structures/CAND-001-fast.cif">mmCIF<{slash}a>
  <dl data-site-metrics="cand-001-fast"><dt>hotspot-contact-fraction<{slash}dt><dd>0.75<{slash}dd><{slash}dl>
<{slash}section>
<{slash}body><{slash}html>\n""".encode()
        report = self.write(root, "report/index.html", html_raw)
        delivery_files = [
            report,
            screenshot,
            render,
            fasta,
            coordinates,
            target,
            target_site_lock,
            plan,
            metrics,
            render_recipe,
        ]
        return {
            "schema_version": MODULE.SCHEMA_VERSION,
            "campaign_id": "delivery-fixture",
            "requirements": {
                "html_report": "required-by-user",
                "sequence_visibility": "required-by-user",
                "structure_visuals": "required-by-user",
                "video": "not-requested",
            },
            "scientific_context": {
                "target_id": "TARGET-1",
                "target_chains": ["T"],
                "site_numbering": "campaign",
                "site_residues": ["T:10", "T:12"],
                "target_coordinates": target,
                "target_site_lock": target_site_lock,
                "plan": plan,
            },
            "candidate_scope": {
                "sequence_kind": "all-generated",
                "structure_kind": "all-predicted",
                "sequence_candidate_ids": [candidate_id],
                "structure_candidate_ids": [candidate_id],
            },
            "report": {
                "html": report,
                "browser_verification": {
                    "status": "passed",
                    "checked_sections": ["overview", "sequences", "structures"],
                    "captures": [
                        {
                            "candidate_id": candidate_id,
                            "render_id": "cand-001-fast",
                            "screenshot": screenshot,
                        }
                    ],
                },
            },
            "viewer_states": {
                "structure": {
                    "packet": "emitted",
                    "runtime": "available",
                    "invocation": "completed",
                    "output_validation": "passed",
                    "outputs": [render],
                },
                "sequence": {
                    "packet": "emitted",
                    "runtime": "available",
                    "invocation": "completed",
                    "output_validation": "passed",
                    "outputs": [fasta],
                },
            },
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "sequence": fasta,
                    "structures": [
                        {
                            "route": "FAL Fast",
                            "render_id": "cand-001-fast",
                            "coordinates": coordinates,
                            "render": render,
                            "metrics": metrics,
                            "site_metrics": site_metrics,
                            "visual_context": {
                                "view_kind": "binder-on-target-site",
                                "target_chains": ["T"],
                                "binder_chains": ["B"],
                                "site_residues": ["T:10", "T:12"],
                                "target_visible": True,
                                "binder_visible": True,
                                "site_highlighted": True,
                                "background": "white",
                                "renderer": "Structure Viewer",
                                "renderer_version": "fixture-1",
                                "render_recipe": render_recipe,
                            },
                        }
                    ],
                }
            ],
            "video": {"storyboard": None, "render": None},
            "delivery_files": delivery_files,
        }

    def test_valid_delivery_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            errors, warnings = MODULE.validate(index, root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_valid_pdb_coordinate_delivery_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            self.replace_coordinates(
                root,
                index,
                self.pdb([("T", 10), ("T", 12), ("B", 1)]),
                suffix=".pdb",
            )
            errors, warnings = MODULE.validate(index, root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_coordinate_artifacts_require_atoms_declared_chains_and_locked_site(self) -> None:
        cases = [
            (
                "empty",
                b"data_empty\n#\n",
                ["coordinates contain no atom records"],
            ),
            (
                "wrong-chain",
                self.mmcif([("X", 10), ("X", 12), ("Y", 1)]),
                [
                    "missing declared target chains: T",
                    "missing declared binder chains: B",
                ],
            ),
            (
                "missing-site",
                self.mmcif([("T", 10), ("B", 1)]),
                ["missing locked target-site residues: T:12"],
            ),
        ]
        for name, coordinate_raw, expected_messages in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                index = self.build_valid(root)
                self.replace_coordinates(root, index, coordinate_raw)
                errors, _ = MODULE.validate(index, root)
                for expected in expected_messages:
                    self.assertTrue(
                        any(expected in item for item in errors),
                        f"missing {expected!r} in {errors!r}",
                    )

    def test_report_must_show_sequence_and_real_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            report_path = root / "report/index.html"
            raw = report_path.read_bytes().replace(b"ACDEFGHIKLMNPQRSTVWY", b"hidden")
            report_path.write_bytes(raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            index["delivery_files"][0] = report_ref
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("show the full FASTA sequence" in item for item in errors))

    def test_storyboard_does_not_satisfy_required_video(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            storyboard = self.write(root, "report/data/storyboard.json", b"{}\n")
            index["requirements"]["video"] = "required-by-user"
            index["video"]["storyboard"] = storyboard
            index["delivery_files"].append(storyboard)
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("storyboard does not satisfy" in item for item in errors))

    def test_structure_visual_must_show_binder_target_and_locked_site(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            visual = index["candidates"][0]["structures"][0]["visual_context"]
            visual["binder_visible"] = False
            visual["site_highlighted"] = False
            visual["background"] = "black"
            visual["site_residues"] = ["T:99"]
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("binder_visible must be true" in item for item in errors))
        self.assertTrue(any("site_highlighted must be true" in item for item in errors))
        self.assertTrue(any("background must be white" in item for item in errors))
        self.assertTrue(any("site_residues must match" in item for item in errors))

    def test_html_image_must_declare_target_binder_site_and_white_background(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            report_path = root / "report/index.html"
            raw = report_path.read_bytes().replace(
                b' data-site-highlighted="true" data-background="white"', b""
            )
            report_path.write_bytes(raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            index["delivery_files"][0] = report_ref
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("data-site-highlighted" in item for item in errors))
        self.assertTrue(any("data-background" in item for item in errors))

    def test_every_render_needs_a_browser_capture_bound_to_its_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            index["report"]["browser_verification"]["captures"][0]["render_id"] = "wrong-render"
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("does not match a delivered candidate render" in item for item in errors))
        self.assertTrue(any("missing a capture for delivered candidate render" in item for item in errors))

    def test_structure_caption_must_name_binder_target_and_locked_site(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            report_path = root / "report/index.html"
            raw = report_path.read_bytes().replace(
                b"CAND-001 binder on TARGET-1 at locked site T:10 and T:12.",
                b"Structure panel.",
            )
            report_path.write_bytes(raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("data-structure-caption" in item for item in errors))

    def test_render_recipe_accepts_extra_camera_and_color_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            recipe_path = root / "report/data/CAND-001-fast-render.json"
            raw = recipe_path.read_bytes().replace(
                b'"height":600}',
                b'"height":600,"camera":{"focus":"target-site"},'
                b'"colors":{"target":"blue","binder":"coral"},'
                b'"representation":"cartoon"}',
            )
            recipe_path.write_bytes(raw)
            recipe_ref = index["candidates"][0]["structures"][0]["visual_context"]["render_recipe"]
            recipe_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            errors, warnings = MODULE.validate(index, root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_site_aware_metrics_must_exist_and_be_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            index["candidates"][0]["structures"][0]["site_metrics"] = []
            report_path = root / "report/index.html"
            raw = report_path.read_bytes().replace(b'data-site-metrics="cand-001-fast"', b"")
            report_path.write_bytes(raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            index["delivery_files"][0] = report_ref
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("site_metrics must contain" in item for item in errors))
        self.assertTrue(any("HTML must show site-aware metrics" in item for item in errors))

    def test_measured_site_metric_value_must_be_finite_numeric(self) -> None:
        invalid_values = [True, "0.75", float("nan"), float("inf"), float("-inf")]
        for value in invalid_values:
            with self.subTest(value=repr(value)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                index = self.build_valid(root)
                self.replace_metric_value(root, index, value)
                errors, _ = MODULE.validate(index, root)
                self.assertTrue(
                    any("finite numeric value" in item for item in errors),
                    f"invalid metric value {value!r} was not rejected: {errors!r}",
                )

    def test_tiny_placeholder_render_and_browser_screenshot_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            render_path = root / "report/media/CAND-001-fast.svg"
            render_raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32"/></svg>\n'
            render_path.write_bytes(render_raw)
            render_ref = index["candidates"][0]["structures"][0]["render"]
            render_ref.update(
                {"sha256": hashlib.sha256(render_raw).hexdigest(), "size_bytes": len(render_raw)}
            )
            screenshot_path = root / "report/browser/full-page.png"
            screenshot_raw = self.png(1, 1)
            screenshot_path.write_bytes(screenshot_raw)
            screenshot_ref = index["report"]["browser_verification"]["captures"][0]["screenshot"]
            screenshot_ref.update(
                {
                    "sha256": hashlib.sha256(screenshot_raw).hexdigest(),
                    "size_bytes": len(screenshot_raw),
                }
            )
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("render must be at least 640x480" in item for item in errors))
        self.assertTrue(any("capture[0].screenshot must be at least 320x200" in item for item in errors))

    def test_rendered_video_must_be_embedded_and_browser_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            video = self.write(
                root, "report/media/campaign.mp4", b"\x00\x00\x00\x18ftypisomfixture"
            )
            index["requirements"]["video"] = "required-by-user"
            index["video"]["render"] = video
            index["delivery_files"].append(video)
            errors, _ = MODULE.validate(index, root)
            self.assertTrue(any("data-campaign-video" in item for item in errors))
            self.assertTrue(any("video-playback" in item for item in errors))

    def test_delivered_video_needs_controls_and_identity_bound_storyboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            video = self.write(
                root, "report/media/campaign.mp4", b"\x00\x00\x00\x18ftypisomfixture"
            )
            index["requirements"]["video"] = "required-by-user"
            index["video"]["render"] = video
            index["delivery_files"].append(video)
            report_path = root / "report/index.html"
            raw = report_path.read_bytes().replace(
                b"</body>",
                b'<video data-campaign-video src="media/campaign.mp4"></video></body>',
            )
            report_path.write_bytes(raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("requires video.storyboard" in item for item in errors))
        self.assertTrue(any("must expose browser controls" in item for item in errors))

    def test_video_storyboard_scenes_must_bind_delivered_candidate_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            video = self.write(
                root, "report/media/campaign.mp4", b"\x00\x00\x00\x18ftypisomfixture"
            )
            storyboard_raw = json.dumps(
                {
                    "schema_version": "codex-binder-video-storyboard/v1",
                    "video_sha256": video["sha256"],
                    "scenes": [
                        {
                            "scene_id": "unknown-site",
                            "candidate_id": "UNKNOWN",
                            "render_id": "unknown-render",
                            "render_sha256": "0" * 64,
                            "start_seconds": 0,
                            "end_seconds": 3,
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode()
            storyboard = self.write(root, "report/data/storyboard.json", storyboard_raw)
            index["requirements"]["video"] = "required-by-user"
            index["video"].update({"render": video, "storyboard": storyboard})
            index["delivery_files"].extend([video, storyboard])
            index["report"]["browser_verification"]["checked_sections"].append("video-playback")
            report_path = root / "report/index.html"
            raw = report_path.read_bytes().replace(
                b"</body>",
                b'<video data-campaign-video data-video-scenes="wrong-site" controls src="media/campaign.mp4"></video></body>',
            )
            report_path.write_bytes(raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            )
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("must bind a delivered candidate/render pair" in item for item in errors))
        self.assertTrue(any("data-video-scenes matching" in item for item in errors))

    def test_complete_video_delivery_with_bound_scene_passes(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("ffmpeg is required to create a valid video fixture")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            video_path = root / "report/media/campaign.mp4"
            made = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white:s=640x480:d=0.2",
                    "-c:v",
                    "mpeg4",
                    "-y",
                    str(video_path),
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(made.returncode, 0, made.stderr)
            video = self.write(root, "report/media/campaign.mp4", video_path.read_bytes())
            structure = index["candidates"][0]["structures"][0]
            storyboard_raw = json.dumps(
                {
                    "schema_version": "codex-binder-video-storyboard/v1",
                    "video_sha256": video["sha256"],
                    "scenes": [
                        {
                            "scene_id": "cand-001-fast-site",
                            "candidate_id": "CAND-001",
                            "render_id": "cand-001-fast",
                            "render_sha256": structure["render"]["sha256"],
                            "start_seconds": 0,
                            "end_seconds": 0.2,
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode()
            storyboard = self.write(root, "report/data/storyboard.json", storyboard_raw)
            index["requirements"]["video"] = "required-by-user"
            index["video"].update({"render": video, "storyboard": storyboard})
            index["delivery_files"].extend([video, storyboard])
            index["report"]["browser_verification"]["checked_sections"].append("video-playback")
            plan_path = root / "plan/codex-binder-plan.json"
            plan_raw = plan_path.read_bytes().replace(
                b'"video":"not-requested"', b'"video":"required-by-user"'
            )
            plan_ref = index["scientific_context"]["plan"]
            plan_ref.update(self.write(root, "plan/codex-binder-plan.json", plan_raw))
            report_path = root / "report/index.html"
            report_raw = report_path.read_bytes().replace(
                b"</body>",
                b'<video data-campaign-video data-video-scenes="cand-001-fast-site" controls src="media/campaign.mp4"></video></body>',
            )
            report_path.write_bytes(report_raw)
            report_ref = index["report"]["html"]
            report_ref.update(
                {
                    "sha256": hashlib.sha256(report_raw).hexdigest(),
                    "size_bytes": len(report_raw),
                }
            )
            errors, warnings = MODULE.validate(index, root)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_curated_delivery_rejects_vendored_workspace_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            vendor_ref = self.write(root, "execution/modal-examples/example.py", b"pass\n")
            index["delivery_files"].append(vendor_ref)
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("non-delivery workspace path" in item for item in errors))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            unexpected = root / "node_modules" / "secret.txt"
            unexpected.parent.mkdir()
            unexpected.write_text("not curated\n", encoding="utf-8")
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("unlisted file" in item for item in errors))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            custom_index = root / "nested" / "custom.json"
            custom_index.parent.mkdir()
            custom_index.write_text("{}\n", encoding="utf-8")
            errors, _ = MODULE.validate(index, root, "nested/custom.json")
            self.assertEqual(errors, [])
            errors, _ = MODULE.validate(index, root, "../outside.json")
            self.assertTrue(any("invalid relative path" in item for item in errors))

    def test_symlinked_delivery_component_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            index = self.build_valid(root)
            sequence_directory = root / "sequences"
            sequence_directory.rename(root / "real-sequences")
            sequence_directory.symlink_to(Path(outside), target_is_directory=True)
            errors, _ = MODULE.validate(index, root)
        self.assertTrue(any("symlinks are forbidden" in item for item in errors))

    def test_symlinked_delivery_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real_root = base / "real"
            real_root.mkdir()
            linked_root = base / "linked"
            linked_root.symlink_to(real_root, target_is_directory=True)
            errors, _ = MODULE.validate({}, linked_root)
        self.assertIn("delivery root must be a non-symlink directory", errors)

    def test_truncated_media_signatures_are_rejected(self) -> None:
        self.assertFalse(MODULE.valid_image(b"\x89PNG\r\n\x1a\nfixture", ".png"))
        self.assertFalse(MODULE.valid_image(b"<svg>", ".svg"))
        self.assertFalse(
            MODULE.valid_image(b"<svg><script>alert(1)</script></svg>", ".svg")
        )
        self.assertFalse(
            MODULE.valid_image(
                b'<svg width="10" height="10"><style>@import url(https://example.invalid/x.css);</style><rect width="10" height="10"/></svg>',
                ".svg",
            )
        )
        self.assertFalse(
            MODULE.valid_image(
                b'<svg width="10" height="10"><rect style="fill:url(https://example.invalid/x)" width="10" height="10"/></svg>',
                ".svg",
            )
        )
        for escaped_css in (
            rb'u\72l(https://example.invalid/pixel)',
            rb'@im\70ort u\72l(https://example.invalid/pixel)',
        ):
            self.assertFalse(
                MODULE.valid_image(
                    b'<svg width="10" height="10"><rect style="fill:red; '
                    + escaped_css
                    + b'" width="10" height="10"/></svg>',
                    ".svg",
                )
            )
        for external_xml in (
            b'<?xml-stylesheet type="text/css" href="https://example.invalid/pixel.css"?><svg width="1" height="1"><rect width="1" height="1"/></svg>',
            b'<!DOCTYPE svg SYSTEM "https://example.invalid/evil.dtd"><svg width="1" height="1"><rect width="1" height="1"/></svg>',
            b'<!ENTITY remote SYSTEM "https://example.invalid/evil.ent"><svg width="1" height="1"><rect width="1" height="1"/></svg>',
        ):
            self.assertFalse(MODULE.valid_image(external_xml, ".svg"))
        self.assertFalse(
            MODULE.valid_image(
                b'<svg width="1" height="1"><image href="#local" width="1" height="1"><set attributeName="href" to="https://example.invalid/pixel" begin="0s"/></image></svg>',
                ".svg",
            )
        )
        self.assertFalse(
            MODULE.valid_image(
                b'<svg width="1" height="1"><rect width="1" height="1"><animate attributeName="fill" to="red"/></rect></svg>',
                ".svg",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.mp4"
            path.write_bytes(b"\x00\x00\x00\x18ftypisomfixture")
            self.assertFalse(MODULE.valid_video(path, ".mp4"))
            path.write_bytes(
                b"\x00\x00\x00\x0cftypisom"
                b"\x00\x00\x00\x08moov"
            )
            self.assertFalse(MODULE.valid_video(path, ".mp4"))
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                valid = Path(directory) / "valid.mp4"
                made = subprocess.run(
                    [
                        ffmpeg,
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=16x16:d=0.2",
                        "-c:v",
                        "mpeg4",
                        "-y",
                        str(valid),
                    ],
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(made.returncode, 0, made.stderr)
                self.assertTrue(MODULE.valid_video(valid, ".mp4"))
                corrupt = bytearray(valid.read_bytes())
                media = corrupt.find(b"mdat")
                self.assertGreater(media, 0)
                corrupt[media + 4 :] = b"\0" * (len(corrupt) - media - 4)
                valid.write_bytes(corrupt)
                self.assertFalse(MODULE.valid_video(valid, ".mp4"))

    def test_decoder_rejects_corrupt_raster_payloads(self) -> None:
        png = bytearray(b"\x89PNG\r\n\x1a\n")
        for chunk_type, payload in (
            (b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)),
            (b"IDAT", b"not-zlib"),
            (b"IEND", b""),
        ):
            png.extend(struct.pack(">I", len(payload)))
            png.extend(chunk_type)
            png.extend(payload)
            png.extend(struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF))
        self.assertFalse(MODULE.valid_image(bytes(png), ".png"))
        self.assertFalse(MODULE.valid_image(b"\xff\xd8" + b"x" * 40 + b"\xff\xd9", ".jpg"))
        self.assertFalse(
            MODULE.valid_image(b"RIFF\x0c\x00\x00\x00WEBParbitrary", ".webp")
        )
        forged_vp8 = b"\x00\x00\x00\x9d\x01\x2a\x00\x00\x00\x00"
        forged_webp = (
            b"RIFF"
            + struct.pack("<I", 4 + 8 + len(forged_vp8))
            + b"WEBPVP8 "
            + struct.pack("<I", len(forged_vp8))
            + forged_vp8
        )
        self.assertFalse(MODULE.valid_image(forged_webp, ".webp"))

    def test_delivery_cannot_drop_sequences_required_by_frozen_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = self.build_valid(root)
            fasta = index["candidates"][0].pop("sequence")
            index["delivery_files"] = [
                ref for ref in index["delivery_files"] if ref["path"] != fasta["path"]
            ]
            (root / fasta["path"]).unlink()
            index["requirements"]["sequence_visibility"] = "not-requested"
            index["viewer_states"]["sequence"] = {
                "packet": "not-emitted",
                "runtime": "unprobed",
                "invocation": "not-run",
                "output_validation": "not-run",
                "outputs": [],
            }
            errors, warnings = MODULE.validate(index, root)
        self.assertTrue(any("sequence_visibility must match the frozen plan" in item for item in errors))
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
