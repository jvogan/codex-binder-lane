from __future__ import annotations

import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_public_export.py"
SPEC = importlib.util.spec_from_file_location("verify_public_export", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class ReleaseSurfaceTests(unittest.TestCase):
    def test_receipt_and_metadata_are_valid(self) -> None:
        count, plugin, marketplace = MODULE.verify_receipt(ROOT)
        name, version = MODULE.verify_metadata(plugin, marketplace)
        self.assertGreater(count, 40)
        self.assertEqual(name, "codex-binder-lane")
        self.assertTrue(version.startswith("0.3.0-rc.1"))

    def test_plugin_manifest_default_prompts_fit_codex_limit(self) -> None:
        _, plugin, _ = MODULE.verify_receipt(ROOT)
        interface = plugin.get("interface")
        self.assertIsInstance(interface, dict)
        assert isinstance(interface, dict)
        prompts = interface.get("defaultPrompt")
        self.assertIsInstance(prompts, list)
        assert isinstance(prompts, list)
        self.assertGreater(len(prompts), 0)
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertIsInstance(prompt, str)
                assert isinstance(prompt, str)
                self.assertLessEqual(len(prompt), 128)

    def test_public_front_door_is_complete(self) -> None:
        required = {
            ".agents/plugins/marketplace.json",
            ".github/workflows/ci.yml",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "README.md",
            "SECURITY.md",
            "docs/release-notes-0.2.0.md",
            "docs/release-notes-0.2.1.md",
            "docs/release-notes-0.3.0-rc.1.md",
            "public-export-receipt.json",
            "scripts/verify_public_export.py",
        }
        self.assertTrue(all((ROOT / path).is_file() for path in required))

    def test_codex_skill_discovery_metadata_is_actionable(self) -> None:
        skill_root = ROOT / "plugins/codex-binder-lane/skills/codex-binder-lane"
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        config = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
        plugin = MODULE.read_json(
            ROOT / "plugins/codex-binder-lane/.codex-plugin/plugin.json"
        )
        public_short_description = (
            "Plan and design binders in Codex—within your comp bio budget"
        )

        frontmatter = skill.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: codex-binder-lane$")
        description = re.search(r"(?m)^description: (.+)$", frontmatter)
        self.assertIsNotNone(description)
        assert description is not None
        for phrase in (
            "Plan, supervise, and validate",
            "chosen target site",
            "binder sequences",
            "target-binder coordinates",
            "site-highlighted visuals",
        ):
            self.assertIn(phrase, description.group(1))

        self.assertIn(f"short-description: {public_short_description}", frontmatter)
        self.assertIn(f'short_description: "{public_short_description}"', config)
        self.assertEqual(
            plugin["interface"]["shortDescription"], public_short_description
        )

        self.assertRegex(
            config,
            r'(?m)^  default_prompt: "[^"]*\$codex-binder-lane[^"]*"$',
        )
        self.assertRegex(config, r"(?m)^  allow_implicit_invocation: true$")
        self.assertTrue(
            (ROOT / "plugins/codex-binder-lane/.codex-plugin/plugin.json").is_file()
        )

    def test_public_prose_has_no_machine_specific_paths(self) -> None:
        for path in ROOT.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for pattern in (
                MODULE.PERSONAL_HOME_RE,
                MODULE.WINDOWS_HOME_RE,
                MODULE.WORKSPACE_DIRECTORY_RE,
            ):
                self.assertIsNone(pattern.search(text), path)

    def test_relative_markdown_links_resolve(self) -> None:
        root = ROOT.resolve()
        for path in ROOT.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for raw_target in MARKDOWN_LINK_RE.findall(text):
                target = raw_target.strip().strip("<>")
                if target.startswith(("#", "mailto:")) or "://" in target:
                    continue
                relative_target = unquote(target.split("#", 1)[0])
                if not relative_target:
                    continue
                resolved = (path.parent / relative_target).resolve()
                self.assertTrue(
                    resolved.is_relative_to(root),
                    f"link escapes release tree: {path} -> {target}",
                )
                self.assertTrue(resolved.exists(), f"broken link: {path} -> {target}")

    def test_verifier_rejects_unreceipted_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy_root = Path(directory) / "release"
            shutil.copytree(ROOT, copy_root)
            (copy_root / "unreceipted.txt").write_text("extra\n", encoding="utf-8")
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify_receipt(copy_root)


if __name__ == "__main__":
    unittest.main()
