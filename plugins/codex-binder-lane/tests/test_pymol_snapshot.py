from __future__ import annotations

import binascii
import importlib.util
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "codex-binder-lane" / "scripts" / "render_locked_pymol_snapshot.py"
SPEC = importlib.util.spec_from_file_location("render_locked_pymol_snapshot", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png_bytes(width: int, height: int, *, include_data: bool = True) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    if include_data:
        rows = (b"\x00" + (b"\x00" * width * 4)) * height
        data += chunk(b"IDAT", zlib.compress(rows))
    return data + chunk(b"IEND", b"")


class PymolSnapshotTests(unittest.TestCase):
    def test_png_validator_requires_pixels_and_fixed_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "snapshot.png"
            output.write_bytes(png_bytes(MODULE.WIDTH, MODULE.HEIGHT))
            data, width, height = MODULE.validate_png(output)
            self.assertTrue(data.startswith(b"\x89PNG"))
            self.assertEqual((width, height), (1280, 720))

            output.write_bytes(png_bytes(MODULE.WIDTH, MODULE.HEIGHT, include_data=False))
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.validate_png(output)

            output.write_bytes(png_bytes(640, 360))
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.validate_png(output)

    def test_render_script_is_fixed_and_has_no_command_input(self) -> None:
        temporary_root = Path("/").joinpath("tmp")
        script = MODULE.render_script(
            temporary_root / "locked.cif", temporary_root / "output.png"
        )
        self.assertIn("cmd.select('target_A', 'locked_complex and segi A')", script)
        self.assertIn("cmd.select('binder_B', 'locked_complex and segi B')", script)
        self.assertIn("within 4.0", script)
        self.assertIn("cmd.draw(1280, 720, antialias=0)", script)
        self.assertNotIn("run ", script)
        self.assertNotIn("@", script)

    def test_locked_source_rejects_any_other_cif(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "other.cif"
            path.write_text("data_OTHER\n", encoding="utf-8")
            with self.assertRaises(MODULE.SnapshotError):
                MODULE.require_locked_cif(path)


if __name__ == "__main__":
    unittest.main()
