from __future__ import annotations

import importlib.util
import json
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
        self.assertEqual(version, "0.3.5")

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

        short_description = interface.get("shortDescription")
        self.assertIsInstance(short_description, str)
        assert isinstance(short_description, str)
        self.assertLessEqual(len(short_description), 30)

        public_copy = " ".join(
            [
                plugin["description"],
                short_description,
                interface["longDescription"],
                *prompts,
            ]
        ).lower()
        for internal_term in (
            "control and evidence layer",
            "execution receipt",
            "provider-neutral",
            "claim ceiling",
        ):
            self.assertNotIn(internal_term, public_copy)
        for user_benefit in (
            "target",
            "constraints",
            "structure",
            "site",
            "tools",
            "routes",
            "campaign size",
            "parallel lanes",
            "filter",
            "iterate",
            "sequences",
            "metrics",
            "visuals",
            "video",
            "report",
        ):
            self.assertIn(user_benefit, public_copy)

    def test_public_front_door_is_complete(self) -> None:
        required = {
            ".agents/plugins/marketplace.json",
            ".github/workflows/ci.yml",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "PRIVACY.md",
            "README.md",
            "SECURITY.md",
            "TERMS.md",
            "docs/openai-submission.json",
            "docs/release-notes-0.2.0.md",
            "docs/release-notes-0.2.1.md",
            "docs/release-notes-0.3.0-rc.1.md",
            "docs/release-notes-0.3.0.md",
            "docs/release-notes-0.3.1.md",
            "docs/release-notes-0.3.2.md",
            "docs/release-notes-0.3.3.md",
            "docs/release-notes-0.3.4.md",
            "docs/release-notes-0.3.5.md",
            "public-export-receipt.json",
            "scripts/verify_public_export.py",
        }
        self.assertTrue(all((ROOT / path).is_file() for path in required))

    def test_shipped_plugin_uses_computational_language(self) -> None:
        plugin_root = ROOT / "plugins/codex-binder-lane"
        forbidden_parts = (
            ("wet", " lab"),
            ("wet", "-lab"),
            ("experi", "ment"),
            ("epi", "tope"),
            ("hot", "spot"),
            ("clin", "ical"),
            ("labora", "tory"),
            ("bio", "safety"),
            ("bio", "security"),
            ("patho", "gen"),
            ("tox", "in"),
            ("wea", "pon"),
            ("cb", "rn"),
        )
        forbidden = tuple("".join(parts) for parts in forbidden_parts)
        text_suffixes = {".csv", ".json", ".md", ".py", ".txt", ".yaml", ".yml"}
        for path in sorted(plugin_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            content = path.read_text(encoding="utf-8").lower()
            for term in forbidden:
                with self.subTest(path=path.relative_to(ROOT), term=term):
                    self.assertNotIn(term, content)

    def test_readme_leads_with_user_outcomes(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "Plan and design binders in Codex: pick target sites, tools and comp bio "
            "budget, then get your structures and sequences.",
            readme,
        )
        public_copy, separator, technical_copy = readme.partition(
            "## Technical details for maintainers"
        )
        self.assertTrue(separator)
        self.assertTrue(technical_copy)

        public_copy = public_copy.lower()
        for internal_term in (
            "control and evidence layer",
            "execution receipt",
            "provider-neutral",
            "claim ceiling",
            "hash-bound",
        ):
            self.assertNotIn(internal_term, public_copy)

        for user_benefit in (
            "binding site",
            "cost",
            "sequence",
            "structure",
            "score",
            "image",
            "raw files",
            "candidate count",
            "parallel lanes",
            "design rounds",
            "cloud",
            "animation",
        ):
            self.assertIn(user_benefit, public_copy)

    def test_codex_skill_discovery_metadata_is_actionable(self) -> None:
        skill_root = ROOT / "plugins/codex-binder-lane/skills/codex-binder-lane"
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        config = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
        plugin = MODULE.read_json(
            ROOT / "plugins/codex-binder-lane/.codex-plugin/plugin.json"
        )
        public_short_description = "Run protein binder campaigns"

        frontmatter = skill.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: codex-binder-lane$")
        description = re.search(r"(?m)^description: (.+)$", frontmatter)
        self.assertIsNotNone(description)
        assert description is not None
        for phrase in (
            "multi-stage protein-binder campaigns",
            "Choose a target structure or site",
            "direct Binder Lane requests",
            "indirect requests",
            "plugins, APIs, cloud compute, local tools, or a mix",
            "Do not use for",
            "one already-specified tool call",
        ):
            self.assertIn(phrase, description.group(1))

        self.assertNotIn("metadata:", frontmatter)
        self.assertNotIn("short-description:", frontmatter)
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

    def test_store_submission_materials_are_complete(self) -> None:
        submission = json.loads(
            (ROOT / "docs/openai-submission.json").read_text(encoding="utf-8")
        )
        plugin = MODULE.read_json(
            ROOT / "plugins/codex-binder-lane/.codex-plugin/plugin.json"
        )
        listing = submission["listing"]
        self.assertEqual(
            submission["schema_version"], "codex-binder-openai-submission/v1"
        )
        self.assertEqual(listing["publisher"], "Jacob Vogan")
        self.assertEqual(listing["type"], "Skills only")
        self.assertEqual(listing["category"], "Scientific Research")
        self.assertEqual(listing["subtitle"], plugin["interface"]["shortDescription"])
        self.assertLessEqual(len(listing["subtitle"]), 30)
        self.assertEqual(
            listing["privacy_url"], plugin["interface"]["privacyPolicyURL"]
        )
        self.assertEqual(listing["terms_url"], plugin["interface"]["termsOfServiceURL"])
        self.assertEqual(
            submission["starter_prompts"], plugin["interface"]["defaultPrompt"]
        )
        self.assertTrue(
            all(len(prompt) <= 128 for prompt in submission["starter_prompts"])
        )

        positives = submission["activation_tests"]["positive"]
        negatives = submission["activation_tests"]["negative"]
        self.assertEqual(len(positives), 5)
        self.assertEqual(len(negatives), 3)
        self.assertEqual(
            {case["activation_class"] for case in positives}, {"direct", "indirect"}
        )
        for case in positives:
            self.assertEqual(
                set(case),
                {
                    "id",
                    "activation_class",
                    "user_prompt",
                    "expected_behavior",
                    "expected_result_shape",
                    "fixture_requirements",
                },
            )
        for case in negatives:
            self.assertEqual(
                set(case),
                {"id", "user_prompt", "expected_behavior", "reason"},
            )

        manifest_assets = ("composerIcon", "logo")
        for field in manifest_assets:
            value = plugin["interface"][field]
            self.assertTrue(value.startswith("./assets/"))
            self.assertTrue((ROOT / "plugins/codex-binder-lane" / value[2:]).is_file())

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
