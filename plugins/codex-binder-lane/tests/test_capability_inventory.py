from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "codex-binder-lane" / "scripts" / "capability_inventory.py"
SPEC = importlib.util.spec_from_file_location("capability_inventory", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CapabilityInventoryTests(unittest.TestCase):
    def test_inventory_recognizes_composable_binder_tools(self) -> None:
        expected = {
            "complexa-target",
            "complexa-design",
            "complexa-sweep",
            "complexa-evaluate-pdbs",
            "openfold2-nim",
            "openfold3-nim",
            "msa-structure-prediction-pipeline",
            "nvmolkit-usage",
        }

        self.assertTrue(expected.issubset(MODULE.RELEVANT_SKILLS))

    def write_driver(self, root: Path, marker: Path) -> Path:
        driver = root / MODULE.BIOSYMPHONY_DRIVER
        driver.parent.mkdir(parents=True)
        driver.write_text(
            "from pathlib import Path\n"
            "import json\n"
            f"Path({str(marker)!r}).write_text('executed\\n', encoding='utf-8')\n"
            "print(json.dumps({\n"
            "    'ok': True,\n"
            "    'profile_id': 'fixture-profile',\n"
            "    'tool_count': 2,\n"
            "    'selectable_count': 1,\n"
            "    'tools': [\n"
            "        {'tool_id': 'selected', 'selectable': True},\n"
            "        {'tool_id': 'blocked', 'selectable': False},\n"
            "    ],\n"
            "}))\n",
            encoding="utf-8",
        )
        return driver

    def run_inventory(
        self,
        workspace: Path,
        home: Path,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "HOME": str(home),
            "PATH": str(Path(sys.executable).parent),
        }
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--workspace",
                str(workspace),
                "--json",
                *args,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_default_inventory_lists_candidate_without_executing_driver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "checkout"
            home = base / "home"
            marker = base / "executed.txt"
            workspace.mkdir()
            home.mkdir()
            self.write_driver(workspace, marker)

            result = self.run_inventory(workspace, home)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["external_code_executed"])
            self.assertFalse(payload["network_or_provider_calls"])
            self.assertIsNone(payload["biosymphony_probe"])
            self.assertFalse(marker.exists())
            self.assertEqual(len(payload["biosymphony"]), 1)
            candidate = payload["biosymphony"][0]
            resolved_workspace = workspace.resolve()
            self.assertEqual(candidate["root"], str(resolved_workspace))
            self.assertEqual(
                candidate["driver"],
                str(resolved_workspace / MODULE.BIOSYMPHONY_DRIVER),
            )
            self.assertFalse(candidate["external_code_executed"])
            self.assertTrue(candidate["probe_allowed"])
            self.assertEqual(payload["codex_plugin_listing"]["status"], "not-probed")

    def test_codex_cli_listing_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with mock.patch.object(
                MODULE,
                "codex_plugin_listing",
                return_value={"ok": True, "marketplaces": []},
            ) as listing:
                default = MODULE.build_inventory(workspace)
                listing.assert_not_called()
                self.assertEqual(default["codex_plugin_listing"]["status"], "not-probed")

                probed = MODULE.build_inventory(workspace, probe_codex_cli=True)
                listing.assert_called_once_with()
                self.assertTrue(probed["external_code_executed"])
                self.assertIsNone(probed["network_or_provider_calls"])

    def test_explicit_probe_executes_only_the_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            selected = base / "selected"
            home = base / "home"
            selected_marker = base / "selected-executed.txt"
            workspace_marker = base / "workspace-executed.txt"
            workspace.mkdir()
            selected.mkdir()
            home.mkdir()
            self.write_driver(workspace, workspace_marker)
            self.write_driver(selected, selected_marker)

            result = self.run_inventory(
                workspace,
                home,
                "--probe-biosymphony-root",
                str(selected),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["external_code_executed"])
            self.assertIsNone(payload["network_or_provider_calls"])
            self.assertTrue(selected_marker.is_file())
            self.assertFalse(workspace_marker.exists())
            probe = payload["biosymphony_probe"]
            self.assertEqual(probe["root"], str(selected))
            self.assertTrue(probe["external_code_executed"])
            self.assertTrue(probe["menu"]["ok"])
            self.assertEqual(probe["menu"]["selectable_tool_ids"], ["selected"])

    def test_probe_rejects_symlinked_root_and_driver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real_root = base / "real-root"
            marker = base / "executed.txt"
            real_root.mkdir()
            driver = self.write_driver(real_root, marker)
            root_link = base / "root-link"
            root_link.symlink_to(real_root, target_is_directory=True)

            with self.assertRaisesRegex(
                MODULE.InventoryError, "root must not be a symlink"
            ):
                MODULE.probe_biosymphony_root(root_link)

            driver.unlink()
            outside_driver = base / "outside-driver.py"
            outside_driver.write_text("print('{}')\n", encoding="utf-8")
            driver.symlink_to(outside_driver)
            with self.assertRaisesRegex(
                MODULE.InventoryError, "driver path must not contain a symlink"
            ):
                MODULE.probe_biosymphony_root(real_root)
            self.assertFalse(marker.exists())

    def test_probe_rejects_invalid_or_inexact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            missing = base / "missing"
            file_root = base / "file-root"
            empty_root = base / "empty-root"
            exact_root = base / "exact-root"
            file_root.write_text("not a directory\n", encoding="utf-8")
            empty_root.mkdir()
            exact_root.mkdir()
            self.write_driver(exact_root, base / "executed.txt")

            cases = (
                (missing, "does not exist"),
                (file_root, "must be a directory"),
                (empty_root, "does not contain the exact driver path"),
                (exact_root / "scripts", "does not contain the exact driver path"),
            )
            for selected, message in cases:
                with (
                    self.subTest(selected=selected),
                    self.assertRaisesRegex(
                        MODULE.InventoryError,
                        message,
                    ),
                ):
                    MODULE.probe_biosymphony_root(selected)

    def test_probe_retains_timeout_and_reports_external_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "selected"
            root.mkdir()
            self.write_driver(root, base / "executed.txt")
            timeout = subprocess.TimeoutExpired(cmd=["fixture"], timeout=60)

            with mock.patch.object(
                MODULE.subprocess, "run", side_effect=timeout
            ) as run:
                result = MODULE.probe_biosymphony_root(root)

            self.assertTrue(result["external_code_executed"])
            self.assertFalse(result["menu"]["ok"])
            self.assertIn("timed out after 60 seconds", result["menu"]["error"])
            self.assertEqual(
                run.call_args.kwargs["timeout"],
                MODULE.BIOSYMPHONY_PROBE_TIMEOUT_SECONDS,
            )


if __name__ == "__main__":
    unittest.main()
