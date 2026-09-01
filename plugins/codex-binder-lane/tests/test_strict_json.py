from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills" / "codex-binder-lane" / "scripts" / "strict_json.py"
SPEC = importlib.util.spec_from_file_location("strict_json", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StrictJSONTests(unittest.TestCase):
    def test_rejects_duplicate_keys(self) -> None:
        with self.assertRaisesRegex(MODULE.StrictJSONError, "duplicate JSON key"):
            MODULE.loads('{"mode":"execute","mode":"plan"}')

    def test_rejects_non_finite_numbers(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(
                MODULE.StrictJSONError, "non-finite JSON number"
            ):
                MODULE.loads(f'{{"value":{value}}}')

    def test_canonical_serialization_is_deterministic_and_finite(self) -> None:
        self.assertEqual(
            MODULE.canonical_bytes({"b": 2, "a": 1}),
            b'{\n  "a": 1,\n  "b": 2\n}\n',
        )
        with self.assertRaises(MODULE.StrictJSONError):
            MODULE.canonical_bytes({"value": math.nan})


if __name__ == "__main__":
    unittest.main()
