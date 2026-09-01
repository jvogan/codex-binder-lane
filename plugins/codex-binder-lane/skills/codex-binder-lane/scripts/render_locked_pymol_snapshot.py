#!/usr/bin/env python3
"""Render one fixed local PyMOL snapshot from the sealed public 1ZVH mmCIF."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ENTRY_ID = "1ZVH"
ENTRY_VERSION = "1.6"
CIF_SIZE_BYTES = 233357
CIF_SHA256 = "6782554510e77d276d5a93e3892bc78136c6bee39b22782f88c874cbf2701226"
EXECUTABLE_NAME = "pymol"
PNG_NAME = "1zvh-pymol.png"
RECEIPT_NAME = "receipt.json"
WIDTH = 1280
HEIGHT = 720
VERSION_RE = re.compile(r"PyMOL\(TM\)\s+([^\s]+)")


class SnapshotError(ValueError):
    """The locked input, local runtime, invocation, or output failed validation."""


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_regular_bytes(path: Path, label: str) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise SnapshotError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SnapshotError(f"{label} must be a regular non-symlink file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SnapshotError(f"cannot read {label}: {exc}") from exc


def require_locked_cif(path: Path) -> tuple[Path, bytes]:
    absolute = path.expanduser().absolute()
    data = read_regular_bytes(absolute, "CIF")
    if len(data) != CIF_SIZE_BYTES or sha256_bytes(data) != CIF_SHA256:
        raise SnapshotError("CIF does not match the sealed 1ZVH v1.6 bytes")
    return absolute, data


def check_output_directory(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.exists():
        if absolute.is_symlink() or not absolute.is_dir():
            raise SnapshotError("output must be an empty non-symlink directory")
        if any(absolute.iterdir()):
            raise SnapshotError("output directory must be empty")
    elif not absolute.parent.is_dir() or absolute.parent.is_symlink():
        raise SnapshotError("output parent must be an existing non-symlink directory")
    return absolute


def resolve_pymol() -> Path:
    resolved = shutil.which(EXECUTABLE_NAME)
    if resolved is None:
        raise SnapshotError("required local executable 'pymol' was not found")
    executable = Path(resolved).resolve()
    if not executable.is_file():
        raise SnapshotError("resolved 'pymol' is not a regular file")
    return executable


def render_script(cif_path: Path, png_path: Path) -> str:
    if not cif_path.is_absolute() or not png_path.is_absolute():
        raise SnapshotError("internal render paths must be absolute")
    return (
        "python\n"
        "from pymol import cmd\n"
        f"source_path = {str(cif_path)!r}\n"
        f"output_path = {str(png_path)!r}\n"
        "cmd.reinitialize()\n"
        "cmd.load(source_path, 'locked_complex')\n"
        "cmd.hide('everything', 'all')\n"
        "cmd.show('cartoon', 'locked_complex and polymer')\n"
        "cmd.color('gray70', 'locked_complex')\n"
        "cmd.select('target_A', 'locked_complex and segi A')\n"
        "cmd.select('binder_B', 'locked_complex and segi B')\n"
        "if cmd.count_atoms('target_A') == 0 or cmd.count_atoms('binder_B') == 0:\n"
        "    raise RuntimeError('locked label-asym chains A/B are missing')\n"
        "cmd.color('cyan', 'target_A')\n"
        "cmd.color('magenta', 'binder_B')\n"
        "cmd.select('interface_target', 'byres (target_A within 4.0 of binder_B)')\n"
        "cmd.select('interface_binder', 'byres (binder_B within 4.0 of target_A)')\n"
        "cmd.show('sticks', 'interface_target or interface_binder')\n"
        "cmd.set('stick_radius', 0.18)\n"
        "cmd.set_color('codex_dark', [0.062745, 0.094118, 0.125490])\n"
        "cmd.bg_color('codex_dark')\n"
        "cmd.set('opaque_background', 1)\n"
        "cmd.set('ray_shadows', 0)\n"
        "cmd.set('antialias', 0)\n"
        "cmd.set('depth_cue', 0)\n"
        f"cmd.viewport({WIDTH}, {HEIGHT})\n"
        "cmd.orient('locked_complex')\n"
        "cmd.zoom('locked_complex', 2.0)\n"
        f"cmd.draw({WIDTH}, {HEIGHT}, antialias=0)\n"
        f"cmd.png(output_path, width={WIDTH}, height={HEIGHT}, dpi=72, ray=0, quiet=1)\n"
        "python end\n"
        "quit\n"
    )


def run_fixed_script(executable: Path, script_path: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(executable), "-cqk", str(script_path)],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError("PyMOL invocation timed out") from exc
    except OSError as exc:
        raise SnapshotError(f"could not invoke PyMOL: {exc}") from exc


def probe_version(executable: Path) -> str:
    try:
        result = subprocess.run(
            [str(executable), "-c", "-d", "quit"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError("PyMOL version probe timed out") from exc
    except OSError as exc:
        raise SnapshotError(f"could not probe PyMOL: {exc}") from exc
    if result.returncode != 0:
        raise SnapshotError("PyMOL version probe failed")
    match = VERSION_RE.search(result.stdout + "\n" + result.stderr)
    if match is None:
        raise SnapshotError("PyMOL version probe returned no parseable version")
    return match.group(1)


def validate_png(path: Path) -> tuple[bytes, int, int]:
    data = read_regular_bytes(path, "PNG output")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SnapshotError("PNG output has an invalid signature")
    offset = 8
    width = height = None
    saw_idat = False
    saw_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise SnapshotError("PNG output has a truncated chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise SnapshotError("PNG output has a truncated chunk payload")
        payload = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if binascii.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            raise SnapshotError("PNG output has a bad chunk checksum")
        if offset == 8:
            if chunk_type != b"IHDR" or length != 13:
                raise SnapshotError("PNG output is missing its fixed IHDR")
            width, height = struct.unpack(">II", payload[:8])
        if chunk_type == b"IDAT" and length > 0:
            saw_idat = True
        if chunk_type == b"IEND":
            if length != 0 or end != len(data):
                raise SnapshotError("PNG output has an invalid terminator")
            saw_iend = True
            break
        offset = end
    if not saw_iend or not saw_idat or width != WIDTH or height != HEIGHT:
        raise SnapshotError(f"PNG output must be exactly {WIDTH}x{HEIGHT}")
    return data, width, height


def render_snapshot(cif: Path, output: Path) -> dict[str, Any]:
    cif_path, cif_bytes = require_locked_cif(cif)
    output_path = check_output_directory(output)
    executable = resolve_pymol()
    with tempfile.TemporaryDirectory(prefix=".pymol-snapshot-", dir=output_path.parent) as temporary:
        working = Path(temporary)
        version = probe_version(executable)
        output_path.mkdir(exist_ok=True)
        png_path = output_path / PNG_NAME
        receipt_path = output_path / RECEIPT_NAME
        render_pml = working / "render.pml"
        render_pml.write_text(render_script(cif_path, png_path), encoding="utf-8")
        try:
            result = run_fixed_script(executable, render_pml, 120)
            if result.returncode != 0:
                raise SnapshotError("PyMOL snapshot invocation failed")
            png_bytes, width, height = validate_png(png_path)
            receipt = {
                "schema_version": "codex-binder-pymol-snapshot-receipt/v1",
                "operation": "fixed-local-snapshot",
                "entry": {"id": ENTRY_ID, "version": ENTRY_VERSION},
                "source": {
                    "name": cif_path.name,
                    "sha256": sha256_bytes(cif_bytes),
                    "size_bytes": len(cif_bytes),
                },
                "renderer": {
                    "executable": EXECUTABLE_NAME,
                    "probe_status": "detected",
                    "version": version,
                    "invocation_status": "succeeded",
                },
                "scene": {
                    "target": {"label_asym_id": "A", "color": "cyan"},
                    "binder": {"label_asym_id": "B", "color": "magenta"},
                    "full_complex_representation": "cartoon",
                    "interface_representation": "sticks",
                    "interface_cutoff_angstrom": 4.0,
                    "background": "#101820",
                    "ray_tracing": False,
                },
                "output": {
                    "path": PNG_NAME,
                    "media_type": "image/png",
                    "width": width,
                    "height": height,
                    "png_signature_valid": True,
                    "sha256": sha256_bytes(png_bytes),
                    "size_bytes": len(png_bytes),
                    "validation_status": "passed",
                },
                "evidence_class": "deposited-visualization",
                "scientific_interpretation": None,
                "observed_cost_usd": 0,
                "claim_ceiling": "transport-proven",
                "actions": {"generation": "not-run", "prediction": "not-run", "network": "not-used"},
            }
            receipt_path.write_bytes(canonical_json_bytes(receipt))
            return receipt
        except (OSError, SnapshotError):
            png_path.unlink(missing_ok=True)
            receipt_path.unlink(missing_ok=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cif", type=Path, help="exact sealed local 1ZVH v1.6 mmCIF")
    parser.add_argument("output", type=Path, help="new or empty output directory")
    args = parser.parse_args()
    try:
        receipt = render_snapshot(args.cif, args.output)
    except (OSError, SnapshotError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"ok": True, "claim_ceiling": receipt["claim_ceiling"], "output": str(args.output)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
