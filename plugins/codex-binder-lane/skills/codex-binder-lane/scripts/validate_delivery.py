#!/usr/bin/env python3
"""Validate a user-facing Binder Lane HTML delivery and its curated index."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import posixpath
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import zlib
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import strict_json  # noqa: E402


SCHEMA_VERSION = "codex-binder-delivery-index/v2"
POSTURES = {"preferred", "required", "required-by-user", "not-requested"}
REQUIRED_POSTURES = {"required", "required-by-user"}
SURFACE_KEYS = {
    "packet": {"not-emitted", "emitted"},
    "runtime": {"unprobed", "available", "unavailable"},
    "invocation": {"not-run", "attempted", "completed", "failed"},
    "output_validation": {"not-run", "pending", "passed", "failed"},
}
FORBIDDEN_DELIVERY_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "modal-examples",
    "node_modules",
    "site-packages",
    "vendor",
}
AA_RE = re.compile(r"^[ABCDEFGHIKLMNPQRSTVWXYZ*]+$")


def finite_numeric(value: Any) -> bool:
    """Return whether value is a finite JSON-style integer or float."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not isinstance(value, float) or math.isfinite(value)


def safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def regular_path(root: Path, relative: str, context: str, errors: list[str]) -> Path | None:
    if not safe_relative_path(relative):
        errors.append(f"{context}: invalid relative path {relative!r}")
        return None
    current = root
    for position, part in enumerate(PurePosixPath(relative).parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            errors.append(f"{context}: cannot inspect {relative}: {exc}")
            return None
        if stat.S_ISLNK(mode):
            errors.append(f"{context}: symlinks are forbidden: {relative}")
            return None
        last = position == len(PurePosixPath(relative).parts) - 1
        if not last and not stat.S_ISDIR(mode):
            errors.append(f"{context}: non-directory path component in {relative}")
            return None
        if last and not stat.S_ISREG(mode):
            errors.append(f"{context}: missing or non-regular file: {relative}")
            return None
    return current


def inventory_delivery_root(root: Path, errors: list[str]) -> set[str]:
    """Inventory the delivery tree without following links or special files."""

    files: set[str] = set()

    def walk(directory: Path, relative: PurePosixPath) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            errors.append(f"delivery inventory: cannot inspect {relative or '.'}: {exc}")
            return
        for entry in entries:
            child_relative = relative / entry.name
            child_path = Path(entry.path)
            try:
                mode = child_path.lstat().st_mode
            except OSError as exc:
                errors.append(f"delivery inventory: cannot inspect {child_relative}: {exc}")
                continue
            if stat.S_ISLNK(mode):
                errors.append(f"delivery inventory: symlinks are forbidden: {child_relative}")
            elif stat.S_ISDIR(mode):
                walk(child_path, child_relative)
            elif stat.S_ISREG(mode):
                files.add(child_relative.as_posix())
            else:
                errors.append(f"delivery inventory: special files are forbidden: {child_relative}")

    walk(root, PurePosixPath())
    return files


def check_ref(
    root: Path,
    value: Any,
    context: str,
    delivery_paths: set[str],
    errors: list[str],
    *,
    load_content: bool = True,
) -> tuple[str | None, bytes | None]:
    if not isinstance(value, dict):
        errors.append(f"{context}: artifact reference must be an object")
        return None, None
    path = value.get("path")
    if not safe_relative_path(path):
        errors.append(f"{context}: invalid relative artifact path {path!r}")
        return None, None
    if path not in delivery_paths:
        errors.append(f"{context}: {path} is absent from curated delivery_files")
    artifact_path = regular_path(root, path, context, errors)
    if artifact_path is None:
        return path, None
    try:
        size = artifact_path.stat().st_size
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        with artifact_path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                if load_content:
                    chunks.append(chunk)
    except OSError as exc:
        errors.append(f"{context}: cannot read {path}: {exc}")
        return path, None
    if value.get("sha256") != digest.hexdigest():
        errors.append(f"{context}: SHA-256 mismatch for {path}")
    if value.get("size_bytes") != size:
        errors.append(f"{context}: byte-count mismatch for {path}")
    return path, b"".join(chunks) if load_content else b""


def coordinate_atom_records(
    raw: bytes,
    suffix: str,
) -> tuple[int, set[str], set[tuple[str, int]]]:
    """Read atom count, chain IDs, and numbered residues from PDB or mmCIF bytes."""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"coordinate file is not UTF-8: {exc}") from exc

    atom_count = 0
    chains: set[str] = set()
    residues: set[tuple[str, int]] = set()
    if suffix == ".pdb":
        for line in text.splitlines():
            if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
                continue
            atom_count += 1
            chain = line[21:22].strip() if len(line) >= 22 else ""
            if not chain:
                continue
            chains.add(chain)
            residue_text = line[22:26].strip() if len(line) >= 26 else ""
            if re.fullmatch(r"[+-]?\d+", residue_text):
                residues.add((chain, int(residue_text)))
        return atom_count, chains, residues

    if suffix not in {".cif", ".mmcif"}:
        raise ValueError("coordinates must be PDB or mmCIF")

    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        lexemes = list(lexer)
    except ValueError as exc:
        raise ValueError(f"malformed mmCIF quoting: {exc}") from exc

    position = 0
    found_atom_loop = False
    while position < len(lexemes):
        if lexemes[position].lower() != "loop_":
            position += 1
            continue
        position += 1
        headers: list[str] = []
        while position < len(lexemes) and lexemes[position].startswith("_"):
            headers.append(lexemes[position])
            position += 1
        if not headers or not any(header.startswith("_atom_site.") for header in headers):
            continue
        if any(not header.startswith("_atom_site.") for header in headers):
            raise ValueError("mmCIF atom-site loop mixes unrelated columns")
        found_atom_loop = True
        values: list[str] = []
        while position < len(lexemes):
            value = lexemes[position]
            lowered = value.lower()
            if (
                lowered == "loop_"
                or lowered == "stop_"
                or lowered.startswith("data_")
                or lowered.startswith("save_")
                or value.startswith("_")
            ):
                break
            values.append(value)
            position += 1
        if len(values) % len(headers) != 0:
            raise ValueError("mmCIF atom-site rows do not match the declared columns")

        header_index = {header: index for index, header in enumerate(headers)}
        group_index = header_index.get("_atom_site.group_PDB")
        label_chain_index = header_index.get("_atom_site.label_asym_id")
        auth_chain_index = header_index.get("_atom_site.auth_asym_id")
        label_residue_index = header_index.get("_atom_site.label_seq_id")
        auth_residue_index = header_index.get("_atom_site.auth_seq_id")
        if label_chain_index is None and auth_chain_index is None:
            raise ValueError("mmCIF atom-site loop has no chain identifier column")
        if label_residue_index is None and auth_residue_index is None:
            raise ValueError("mmCIF atom-site loop has no residue-number column")

        for offset in range(0, len(values), len(headers)):
            row = values[offset : offset + len(headers)]
            if group_index is not None and row[group_index].upper() not in {"ATOM", "HETATM"}:
                continue
            atom_count += 1
            chain = ""
            for index in (label_chain_index, auth_chain_index):
                if index is not None and row[index] not in {".", "?"}:
                    chain = row[index]
                    break
            if not chain:
                continue
            chains.add(chain)
            residue_text = ""
            for index in (label_residue_index, auth_residue_index):
                if index is not None and row[index] not in {".", "?"}:
                    residue_text = row[index]
                    break
            if re.fullmatch(r"[+-]?\d+", residue_text):
                residues.add((chain, int(residue_text)))

    if not found_atom_loop:
        return 0, set(), set()
    return atom_count, chains, residues


def check_coordinate_content(
    raw: bytes,
    suffix: str,
    target_chains: list[str],
    binder_chains: list[str],
    site_residues: list[str],
    context: str,
    errors: list[str],
) -> None:
    try:
        atom_count, present_chains, present_residues = coordinate_atom_records(raw, suffix)
    except ValueError as exc:
        errors.append(f"{context}: {exc}")
        return
    if atom_count == 0:
        errors.append(f"{context}: coordinates contain no atom records")
        return

    missing_targets = sorted(set(target_chains) - present_chains)
    if missing_targets:
        errors.append(
            f"{context}: coordinates are missing declared target chains: {', '.join(missing_targets)}"
        )
    missing_binders = sorted(set(binder_chains) - present_chains)
    if missing_binders:
        errors.append(
            f"{context}: coordinates are missing declared binder chains: {', '.join(missing_binders)}"
        )

    expected_sites: dict[tuple[str, int], str] = {}
    for site in site_residues:
        chain, separator, residue_text = site.rpartition(":")
        if not separator or not chain or re.fullmatch(r"[+-]?\d+", residue_text) is None:
            errors.append(f"{context}: invalid locked target-site residue {site!r}")
            continue
        expected_sites[(chain, int(residue_text))] = site
    missing_sites = sorted(
        expected_sites[site] for site in expected_sites.keys() - present_residues
    )
    if missing_sites:
        errors.append(
            f"{context}: coordinates are missing locked target-site residues: "
            + ", ".join(missing_sites)
        )


def fasta_sequence(
    raw: bytes,
    context: str,
    errors: list[str],
    expected_record_id: str | None = None,
) -> str | None:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        errors.append(f"{context}: FASTA is not UTF-8: {exc}")
        return None
    headers = [index for index, line in enumerate(lines) if line.startswith(">")]
    if len(headers) != 1 or headers[0] != 0:
        errors.append(f"{context}: candidate FASTA must contain exactly one record")
        return None
    record_id = lines[0][1:].strip().split(maxsplit=1)[0] if lines[0][1:].strip() else ""
    if expected_record_id is not None and record_id != expected_record_id:
        errors.append(
            f"{context}: FASTA record ID {record_id!r} must match candidate_id {expected_record_id!r}"
        )
    sequence = "".join(line.strip() for line in lines[1:] if line.strip()).upper()
    if not sequence or AA_RE.fullmatch(sequence) is None:
        errors.append(f"{context}: candidate FASTA has an invalid or empty protein sequence")
        return None
    return sequence


def raster_decoder_accepts(raw: bytes) -> bool:
    """Require a full raster frame decode when stdlib cannot decode it."""

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-nostdin",
                "-f",
                "image2pipe",
                "-i",
                "pipe:0",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            input=raw,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def valid_image(raw: bytes, suffix: str) -> bool:
    suffix = suffix.lower()
    if suffix == ".png":
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        position = 8
        seen_ihdr = seen_idat = seen_iend = False
        image_data = bytearray()
        scanline_bytes = height = 0
        while position + 12 <= len(raw):
            length = struct.unpack(">I", raw[position : position + 4])[0]
            chunk_type = raw[position + 4 : position + 8]
            end = position + 12 + length
            if end > len(raw):
                return False
            payload = raw[position + 8 : position + 8 + length]
            expected_crc = struct.unpack(">I", raw[position + 8 + length : end])[0]
            if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
                return False
            if not seen_ihdr:
                if chunk_type != b"IHDR" or length != 13:
                    return False
                width, height = struct.unpack(">II", payload[:8])
                if width == 0 or height == 0:
                    return False
                bit_depth, color_type, compression, filter_method, interlace = payload[8:13]
                channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
                valid_depths = {
                    0: {1, 2, 4, 8, 16},
                    2: {8, 16},
                    3: {1, 2, 4, 8},
                    4: {8, 16},
                    6: {8, 16},
                }
                if (
                    channels is None
                    or bit_depth not in valid_depths[color_type]
                    or compression != 0
                    or filter_method != 0
                    or interlace != 0
                ):
                    return False
                scanline_bytes = (width * channels * bit_depth + 7) // 8
                seen_ihdr = True
            elif chunk_type == b"IDAT":
                seen_idat = True
                image_data.extend(payload)
            elif chunk_type == b"IEND":
                seen_iend = length == 0 and end == len(raw)
                break
            position = end
        if not (seen_ihdr and seen_idat and seen_iend):
            return False
        try:
            pixels = zlib.decompress(bytes(image_data))
        except zlib.error:
            return False
        row_size = scanline_bytes + 1
        return len(pixels) == row_size * height and all(
            pixels[row * row_size] <= 4 for row in range(height)
        )
    if suffix in {".jpg", ".jpeg"}:
        if len(raw) < 32 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
            return False
        position = 2
        saw_frame = False
        while position + 1 < len(raw):
            if raw[position] != 0xFF:
                return False
            while position < len(raw) and raw[position] == 0xFF:
                position += 1
            if position >= len(raw):
                return False
            marker = raw[position]
            position += 1
            if marker == 0xD9:
                return False
            if marker in {0x01, *range(0xD0, 0xD8)}:
                continue
            if position + 2 > len(raw):
                return False
            length = struct.unpack(">H", raw[position : position + 2])[0]
            if length < 2 or position + length > len(raw):
                return False
            payload = raw[position + 2 : position + length]
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if len(payload) < 6:
                    return False
                frame_height, frame_width = struct.unpack(">HH", payload[1:5])
                if frame_width == 0 or frame_height == 0:
                    return False
                saw_frame = True
            if marker == 0xDA:
                scan_start = position + length
                eoi = raw.rfind(b"\xff\xd9")
                return (
                    saw_frame
                    and eoi == len(raw) - 2
                    and eoi - scan_start >= 4
                    and raster_decoder_accepts(raw)
                )
            position += length
        return False
    if suffix == ".webp":
        if (
            len(raw) < 30
            or raw[:4] != b"RIFF"
            or raw[8:12] != b"WEBP"
            or struct.unpack("<I", raw[4:8])[0] + 8 != len(raw)
        ):
            return False
        position = 12
        saw_image = False
        while position + 8 <= len(raw):
            chunk_type = raw[position : position + 4]
            length = struct.unpack("<I", raw[position + 4 : position + 8])[0]
            start = position + 8
            end = start + length
            if end > len(raw):
                return False
            payload = raw[start:end]
            if chunk_type == b"VP8 ":
                saw_image = len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a"
            elif chunk_type == b"VP8L":
                saw_image = len(payload) >= 5 and payload[0] == 0x2F
            elif chunk_type == b"ANMF":
                saw_image = len(payload) >= 24
            position = end + (length & 1)
        return position == len(raw) and saw_image and raster_decoder_accepts(raw)
    if suffix == ".svg":
        lowered_raw = raw.lower()
        if any(
            marker in lowered_raw
            for marker in (b"<?xml-stylesheet", b"<!doctype", b"<!entity")
        ):
            return False
        try:
            root = ElementTree.fromstring(raw)
        except (ElementTree.ParseError, UnicodeDecodeError):
            return False
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            return False
        static_tags = {
            "circle",
            "clippath",
            "defs",
            "desc",
            "ellipse",
            "g",
            "image",
            "line",
            "mask",
            "path",
            "polygon",
            "polyline",
            "rect",
            "svg",
            "text",
            "title",
            "tspan",
            "use",
        }
        has_canvas = any(root.get(name) for name in ("width", "height", "viewBox"))
        has_visible_element = False
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if tag not in static_tags:
                return False
            for key, value in element.attrib.items():
                attribute = key.rsplit("}", 1)[-1].lower()
                if attribute.startswith("on"):
                    return False
                if attribute == "style":
                    return False
                if attribute == "base":
                    return False
                if attribute == "href" and value.strip() and not value.strip().startswith("#"):
                    return False
                lowered_value = value.casefold()
                if "\\" in value or "url(" in lowered_value or "@import" in lowered_value:
                    return False
            if tag in {"circle", "ellipse", "image", "line", "path", "polygon", "polyline", "rect", "text", "use"}:
                has_visible_element = True
        return has_canvas and has_visible_element
    return False


def image_dimensions(path: Path, raw: bytes) -> tuple[int, int] | None:
    """Return validated image dimensions for render-size acceptance checks."""

    suffix = path.suffix.lower()
    if suffix == ".png" and len(raw) >= 24 and raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", raw[16:24])
    if suffix == ".svg":
        try:
            root = ElementTree.fromstring(raw)
        except (ElementTree.ParseError, UnicodeDecodeError):
            return None

        def number(value: str | None) -> int | None:
            if not isinstance(value, str):
                return None
            match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
            if match is None:
                return None
            parsed = float(match.group(1))
            return int(parsed) if parsed > 0 else None

        width, height = number(root.get("width")), number(root.get("height"))
        if width and height:
            return width, height
        view_box = root.get("viewBox")
        if isinstance(view_box, str):
            try:
                _, _, view_width, view_height = [float(item) for item in view_box.replace(",", " ").split()]
            except (TypeError, ValueError):
                return None
            if view_width > 0 and view_height > 0:
                return int(view_width), int(view_height)
        return None
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        return None
    width, height = streams[0].get("width"), streams[0].get("height")
    if isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0:
        return width, height
    return None


def valid_video(path: Path, suffix: str) -> bool:
    try:
        total_size = path.stat().st_size
    except OSError:
        return False
    suffix = suffix.lower()
    if suffix not in {".mp4", ".m4v", ".webm"} or total_size < 32:
        return False
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return False
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,width,height,duration,nb_frames:format=duration,format_name",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False
        probe = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False
    streams = probe.get("streams") if isinstance(probe, dict) else None
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        return False
    stream = streams[0]
    if (
        stream.get("codec_type") != "video"
        or not isinstance(stream.get("width"), int)
        or stream["width"] <= 0
        or not isinstance(stream.get("height"), int)
        or stream["height"] <= 0
    ):
        return False
    durations = [stream.get("duration")]
    format_record = probe.get("format")
    if isinstance(format_record, dict):
        durations.append(format_record.get("duration"))
    has_duration = False
    for value in durations:
        try:
            has_duration = has_duration or float(value) > 0
        except (TypeError, ValueError):
            pass
    try:
        has_frames = int(stream.get("nb_frames")) > 0
    except (TypeError, ValueError):
        has_frames = False
    if not (has_duration or has_frames):
        return False
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return False
    try:
        decoded = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-xerror",
                "-nostdin",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return decoded.returncode == 0


def resolve_html_path(report_path: str, href: str | None) -> str | None:
    if not isinstance(href, str) or not href or "://" in href or href.startswith("data:"):
        return None
    href = html.unescape(href).split("#", 1)[0].split("?", 1)[0]
    normalized = posixpath.normpath(posixpath.join(posixpath.dirname(report_path), href))
    return normalized if safe_relative_path(normalized) else None


class EvidenceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sequence_text: dict[str, str] = {}
        self.sequence_links: dict[str, str] = {}
        self.structure_images: dict[str, dict[str, str | None]] = {}
        self.structure_links: dict[str, str] = {}
        self.structure_captions: dict[str, str] = {}
        self.site_metric_text: dict[str, str] = {}
        self.videos: list[dict[str, Any]] = []
        self._sequence_id: str | None = None
        self._sequence_parts: list[str] = []
        self._site_metric_id: str | None = None
        self._site_metric_tag: str | None = None
        self._site_metric_parts: list[str] = []
        self._structure_caption_id: str | None = None
        self._structure_caption_tag: str | None = None
        self._structure_caption_parts: list[str] = []
        self._active_campaign_video: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "code" and values.get("data-binder-sequence"):
            self._sequence_id = values["data-binder-sequence"]
            self._sequence_parts = []
        if tag == "a" and values.get("data-sequence-download") and values.get("href"):
            self.sequence_links[values["data-sequence-download"]] = values["href"]
        if tag == "img" and values.get("data-structure-render") and values.get("src"):
            self.structure_images[values["data-structure-render"]] = values
        if tag == "a" and values.get("data-structure-download") and values.get("href"):
            self.structure_links[values["data-structure-download"]] = values["href"]
        if values.get("data-structure-caption"):
            self._structure_caption_id = values["data-structure-caption"]
            self._structure_caption_tag = tag
            self._structure_caption_parts = []
        if values.get("data-site-metrics"):
            self._site_metric_id = values["data-site-metrics"]
            self._site_metric_tag = tag
            self._site_metric_parts = []
        if tag == "video" and "data-campaign-video" in values:
            self.videos.append(
                {
                    "src": values.get("src"),
                    "controls": "controls" in values,
                    "scene_ids": values.get("data-video-scenes"),
                }
            )
            self._active_campaign_video = len(self.videos) - 1
        elif tag == "source" and self._active_campaign_video is not None:
            if self.videos[self._active_campaign_video].get("src") is None:
                self.videos[self._active_campaign_video]["src"] = values.get("src")
        elif tag == "source" and "data-campaign-video" in values:
            self.videos.append(
                {
                    "src": values.get("src"),
                    "controls": False,
                    "scene_ids": values.get("data-video-scenes"),
                }
            )

    def handle_data(self, data: str) -> None:
        if self._sequence_id is not None:
            self._sequence_parts.append(data)
        if self._site_metric_id is not None:
            self._site_metric_parts.append(data)
        if self._structure_caption_id is not None:
            self._structure_caption_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "code" and self._sequence_id is not None:
            self.sequence_text[self._sequence_id] = "".join(self._sequence_parts)
            self._sequence_id = None
            self._sequence_parts = []
        if tag == self._site_metric_tag and self._site_metric_id is not None:
            self.site_metric_text[self._site_metric_id] = "".join(self._site_metric_parts)
            self._site_metric_id = None
            self._site_metric_tag = None
            self._site_metric_parts = []
        if tag == self._structure_caption_tag and self._structure_caption_id is not None:
            self.structure_captions[self._structure_caption_id] = "".join(
                self._structure_caption_parts
            )
            self._structure_caption_id = None
            self._structure_caption_tag = None
            self._structure_caption_parts = []
        if tag == "video":
            self._active_campaign_video = None


def validate_surface(name: str, value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"viewer_states.{name} must be an object")
        return
    for key, allowed in SURFACE_KEYS.items():
        if value.get(key) not in allowed:
            errors.append(f"viewer_states.{name}.{key} must be one of {sorted(allowed)}")
    runtime = value.get("runtime")
    invocation = value.get("invocation")
    validation = value.get("output_validation")
    outputs = value.get("outputs")
    if not isinstance(outputs, list):
        errors.append(f"viewer_states.{name}.outputs must be an array")
        outputs = []
    if runtime in {"unprobed", "unavailable"} and invocation == "completed":
        errors.append(f"viewer_states.{name}: completed invocation requires available runtime")
    if invocation == "not-run" and outputs:
        errors.append(f"viewer_states.{name}: not-run invocation cannot declare outputs")
    if validation == "passed" and not outputs:
        errors.append(f"viewer_states.{name}: passed output validation requires outputs")


def validate(
    index: Any,
    root: Path,
    index_relative: str | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        return [f"delivery root cannot be inspected: {exc}"], warnings
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        return ["delivery root must be a non-symlink directory"], warnings
    if not isinstance(index, dict):
        return ["delivery index root must be an object"], warnings
    if index.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(index.get("campaign_id"), str) or not index["campaign_id"].strip():
        errors.append("campaign_id must be a non-empty string")

    requirements = index.get("requirements")
    if not isinstance(requirements, dict):
        errors.append("requirements must be an object")
        requirements = {}
    for field in ("html_report", "sequence_visibility", "structure_visuals", "video"):
        if requirements.get(field) not in POSTURES:
            errors.append(f"requirements.{field} must be one of {sorted(POSTURES)}")

    scientific_context = index.get("scientific_context")
    if not isinstance(scientific_context, dict):
        errors.append("scientific_context must be an object")
        scientific_context = {}
    for field in ("target_id", "site_numbering"):
        value = scientific_context.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"scientific_context.{field} must be a non-empty string")
    target_chains = scientific_context.get("target_chains")
    if (
        not isinstance(target_chains, list)
        or not target_chains
        or any(not isinstance(value, str) or not value.strip() for value in target_chains)
        or len(set(target_chains)) != len(target_chains)
    ):
        errors.append("scientific_context.target_chains must be a non-empty unique string array")
        target_chains = []
    site_residues = scientific_context.get("site_residues")
    if (
        not isinstance(site_residues, list)
        or not site_residues
        or any(not isinstance(value, str) or not value.strip() for value in site_residues)
        or len(set(site_residues)) != len(site_residues)
    ):
        errors.append("scientific_context.site_residues must be a non-empty unique string array")
        site_residues = []

    delivery_files = index.get("delivery_files")
    if not isinstance(delivery_files, list) or not delivery_files:
        errors.append("delivery_files must be a non-empty array of artifact references")
        delivery_files = []
    delivery_paths: set[str] = set()
    for position, ref in enumerate(delivery_files):
        if not isinstance(ref, dict) or not safe_relative_path(ref.get("path")):
            errors.append(f"delivery_files[{position}] has an invalid artifact path")
            continue
        path = ref["path"]
        if path in delivery_paths:
            errors.append(f"delivery_files contains duplicate path: {path}")
        delivery_paths.add(path)
        forbidden = FORBIDDEN_DELIVERY_PARTS.intersection(PurePosixPath(path).parts)
        if forbidden:
            errors.append(f"delivery_files contains non-delivery workspace path: {path}")
    actual_files = inventory_delivery_root(root, errors)
    allowed_files = set(delivery_paths)
    if index_relative is not None:
        if not safe_relative_path(index_relative):
            errors.append(f"delivery index has an invalid relative path: {index_relative!r}")
        elif index_relative in actual_files:
            allowed_files.add(index_relative)
    elif "delivery-index.json" in actual_files:
        allowed_files.add("delivery-index.json")
    for extra in sorted(actual_files - allowed_files):
        errors.append(f"delivery inventory contains unlisted file: {extra}")
    for position, ref in enumerate(delivery_files):
        check_ref(
            root,
            ref,
            f"delivery_files[{position}]",
            delivery_paths,
            errors,
            load_content=False,
        )

    target_path, _ = check_ref(
        root,
        scientific_context.get("target_coordinates"),
        "scientific_context.target_coordinates",
        delivery_paths,
        errors,
        load_content=False,
    )
    if target_path and Path(target_path).suffix.lower() not in {".cif", ".mmcif", ".pdb"}:
        errors.append("scientific_context.target_coordinates must be PDB or mmCIF")
    _, target_lock_raw = check_ref(
        root,
        scientific_context.get("target_site_lock"),
        "scientific_context.target_site_lock",
        delivery_paths,
        errors,
    )
    if target_lock_raw is not None:
        try:
            target_lock = strict_json.loads(target_lock_raw)
        except strict_json.StrictJSONError as exc:
            errors.append(f"scientific_context.target_site_lock is not strict JSON: {exc}")
        else:
            if not isinstance(target_lock, dict):
                errors.append("scientific_context.target_site_lock must contain a JSON object")
            else:
                if target_lock.get("campaign_id") != index.get("campaign_id"):
                    errors.append("target/site lock campaign_id must match delivery campaign_id")
                if target_lock.get("target_id") != scientific_context.get("target_id"):
                    errors.append("scientific_context.target_id must match the target/site lock")
                locked_target_chains = [
                    chain.get("campaign_chain_id")
                    for chain in target_lock.get("chains", [])
                    if isinstance(chain, dict) and chain.get("role") == "target"
                ]
                if target_chains != locked_target_chains:
                    errors.append("scientific_context.target_chains must match target chains in the target/site lock")
                locked_site = target_lock.get("site")
                if not isinstance(locked_site, dict):
                    errors.append("target/site lock site must be an object")
                else:
                    if scientific_context.get("site_numbering") != locked_site.get("numbering_scheme"):
                        errors.append("scientific_context.site_numbering must match the target/site lock")
                    locked_residues = [
                        f"{residue.get('campaign_chain_id')}:{residue.get('campaign_residue_number')}"
                        for residue in locked_site.get("residues", [])
                        if isinstance(residue, dict)
                    ]
                    if site_residues != locked_residues:
                        errors.append("scientific_context.site_residues must match the target/site lock")
                primary_input = target_lock.get("primary_input")
                target_ref = scientific_context.get("target_coordinates")
                if not isinstance(primary_input, dict) or not isinstance(target_ref, dict):
                    errors.append("target/site lock primary_input must match target_coordinates")
                elif any(
                    primary_input.get(field) != target_ref.get(field)
                    for field in ("path", "sha256", "size_bytes")
                ):
                    errors.append("scientific_context.target_coordinates must match target/site lock primary_input")

    _, plan_raw = check_ref(
        root,
        scientific_context.get("plan"),
        "scientific_context.plan",
        delivery_paths,
        errors,
    )
    if plan_raw is not None:
        try:
            frozen_plan = strict_json.loads(plan_raw)
        except strict_json.StrictJSONError as exc:
            errors.append(f"scientific_context.plan is not strict JSON: {exc}")
        else:
            if not isinstance(frozen_plan, dict):
                errors.append("scientific_context.plan must contain a JSON object")
            else:
                if frozen_plan.get("campaign_id") != index.get("campaign_id"):
                    errors.append("frozen plan campaign_id must match delivery campaign_id")
                plan_presentation = (
                    frozen_plan.get("evidence", {}).get("presentation", {})
                    if isinstance(frozen_plan.get("evidence"), dict)
                    else {}
                )
                if not isinstance(plan_presentation, dict):
                    errors.append("frozen plan evidence.presentation must be an object")
                    plan_presentation = {}
                for field in ("html_report", "sequence_visibility", "structure_visuals", "video"):
                    if requirements.get(field) != plan_presentation.get(field):
                        errors.append(f"requirements.{field} must match the frozen plan")
                expected_sequence_kind = plan_presentation.get("sequence_scope")
                expected_structure_kind = plan_presentation.get("structure_scope")
                if expected_sequence_kind not in {"all-generated", "delivered"}:
                    expected_sequence_kind = None
                if expected_structure_kind == "promoted":
                    expected_structure_kind = "delivered"
                elif expected_structure_kind not in {"all-predicted", "delivered"}:
                    expected_structure_kind = None
                declared_scope = index.get("candidate_scope")
                if isinstance(declared_scope, dict):
                    if expected_sequence_kind and declared_scope.get("sequence_kind") != expected_sequence_kind:
                        errors.append("candidate_scope.sequence_kind must match the frozen plan")
                    if expected_structure_kind and declared_scope.get("structure_kind") != expected_structure_kind:
                        errors.append("candidate_scope.structure_kind must match the frozen plan")
                plan_target = frozen_plan.get("target")
                if isinstance(plan_target, dict):
                    if plan_target.get("identifier") != scientific_context.get("target_id"):
                        errors.append("scientific_context.target_id must match the frozen plan")
                    plan_lock = plan_target.get("target_lock")
                    delivery_lock = scientific_context.get("target_site_lock")
                    if isinstance(plan_lock, dict) and isinstance(delivery_lock, dict):
                        if any(
                            plan_lock.get(field) != delivery_lock.get(field)
                            for field in ("path", "sha256", "size_bytes")
                        ):
                            errors.append("scientific_context.target_site_lock must match the frozen plan")

    report = index.get("report")
    if not isinstance(report, dict):
        errors.append("report must be an object")
        report = {}
    report_path, report_raw = check_ref(
        root, report.get("html"), "report.html", delivery_paths, errors
    )
    markdown = report.get("markdown")
    if markdown is not None:
        check_ref(
            root,
            markdown,
            "report.markdown",
            delivery_paths,
            errors,
            load_content=False,
        )
    parser = EvidenceHTMLParser()
    if report_raw is not None and report_path is not None:
        try:
            parser.feed(report_raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            errors.append(f"report.html: report is not UTF-8: {exc}")

    browser = report.get("browser_verification")
    if not isinstance(browser, dict) or browser.get("status") != "passed":
        errors.append("report.browser_verification.status must be passed")
        browser = {}
    checked_sections = browser.get("checked_sections")
    required_sections = {"overview"}
    if requirements.get("sequence_visibility") != "not-requested":
        required_sections.add("sequences")
    if requirements.get("structure_visuals") != "not-requested":
        required_sections.add("structures")
    if not isinstance(checked_sections, list) or not required_sections.issubset(checked_sections):
        errors.append(
            "browser verification is missing required sections: "
            + ", ".join(sorted(required_sections))
        )
    captures = browser.get("captures")
    if not isinstance(captures, list):
        errors.append("browser verification.captures must be an array")
        captures = []
    browser_capture_pairs: list[tuple[str, str]] = []
    for position, capture in enumerate(captures):
        context = f"browser capture[{position}]"
        if not isinstance(capture, dict):
            errors.append(f"{context} must be an object")
            continue
        candidate_id = capture.get("candidate_id")
        render_id = capture.get("render_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            errors.append(f"{context}.candidate_id must be a non-empty string")
        if not isinstance(render_id, str) or not render_id.strip():
            errors.append(f"{context}.render_id must be a non-empty string")
        if isinstance(candidate_id, str) and candidate_id.strip() and isinstance(render_id, str) and render_id.strip():
            browser_capture_pairs.append((candidate_id, render_id))
        path, raw = check_ref(
            root, capture.get("screenshot"), f"{context}.screenshot", delivery_paths, errors
        )
        if path and raw is not None and not valid_image(raw, Path(path).suffix):
            errors.append(f"{context}.screenshot is not a validated image: {path}")
        elif path and raw is not None:
            dimensions = image_dimensions(root / path, raw)
            if dimensions is None or dimensions[0] < 320 or dimensions[1] < 200:
                errors.append(
                    f"{context}.screenshot must be at least 320x200 pixels: {path}"
                )

    viewers = index.get("viewer_states")
    if not isinstance(viewers, dict):
        errors.append("viewer_states must be an object")
        viewers = {}
    for name in ("structure", "sequence"):
        validate_surface(name, viewers.get(name), errors)
        value = viewers.get(name)
        if isinstance(value, dict):
            for position, ref in enumerate(value.get("outputs", [])):
                check_ref(
                    root,
                    ref,
                    f"viewer_states.{name}.outputs[{position}]",
                    delivery_paths,
                    errors,
                    load_content=False,
                )

    candidates = index.get("candidates")
    if not isinstance(candidates, list):
        errors.append("candidates must be an array")
        candidates = []
    scope = index.get("candidate_scope")
    if not isinstance(scope, dict):
        errors.append("candidate_scope must be an object")
        scope = {}
    if scope.get("sequence_kind") not in {"all-generated", "delivered"}:
        errors.append("candidate_scope.sequence_kind must be all-generated or delivered")
    if scope.get("structure_kind") not in {"all-predicted", "delivered"}:
        errors.append("candidate_scope.structure_kind must be all-predicted or delivered")
    sequence_candidate_ids = scope.get("sequence_candidate_ids")
    structure_candidate_ids = scope.get("structure_candidate_ids")
    for field, values in (
        ("sequence_candidate_ids", sequence_candidate_ids),
        ("structure_candidate_ids", structure_candidate_ids),
    ):
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value.strip() for value in values)
            or len(set(values)) != len(values)
        ):
            errors.append(f"candidate_scope.{field} must be a unique string array")
    if not isinstance(sequence_candidate_ids, list):
        sequence_candidate_ids = []
    if not isinstance(structure_candidate_ids, list):
        structure_candidate_ids = []
    if not set(structure_candidate_ids).issubset(sequence_candidate_ids):
        errors.append("candidate_scope.structure_candidate_ids must be a subset of sequence_candidate_ids")

    seen_candidates: set[str] = set()
    rendered_pairs: set[tuple[str, str]] = set()
    render_sha256_by_pair: dict[tuple[str, str], str] = {}
    for position, candidate in enumerate(candidates):
        context = f"candidates[{position}]"
        if not isinstance(candidate, dict):
            errors.append(f"{context} must be an object")
            continue
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            errors.append(f"{context}.candidate_id must be a non-empty string")
            continue
        if candidate_id in seen_candidates:
            errors.append(f"duplicate candidate_id: {candidate_id}")
        seen_candidates.add(candidate_id)
        sequence_ref = candidate.get("sequence")
        sequence_required = requirements.get("sequence_visibility") != "not-requested"
        if sequence_required or sequence_ref is not None:
            sequence_path, sequence_raw = check_ref(
                root, sequence_ref, f"{context}.sequence", delivery_paths, errors
            )
        else:
            sequence_path, sequence_raw = None, None
        sequence = (
            fasta_sequence(
                sequence_raw,
                f"{context}.sequence",
                errors,
                expected_record_id=candidate_id,
            )
            if sequence_raw
            else None
        )
        visible = re.sub(r"\s+", "", parser.sequence_text.get(candidate_id, "")).upper()
        if sequence and visible != sequence:
            errors.append(
                f"{context}: HTML must show the full FASTA sequence in "
                f'<code data-binder-sequence="{candidate_id}">'
            )
        linked = resolve_html_path(report_path, parser.sequence_links.get(candidate_id)) if report_path else None
        if sequence_path and linked != sequence_path:
            errors.append(
                f"{context}: HTML must link the FASTA with "
                f'data-sequence-download="{candidate_id}"'
            )

        structures = candidate.get("structures")
        if not isinstance(structures, list):
            errors.append(f"{context}.structures must be an array")
            structures = []
        structure_in_scope = candidate_id in structure_candidate_ids
        if (
            requirements.get("structure_visuals") in REQUIRED_POSTURES
            and structure_in_scope
            and not structures
        ):
            errors.append(f"{context}: required structure visuals are missing")
        if structures and not structure_in_scope:
            errors.append(f"{context}: structures exist but candidate is absent from structure scope")
        seen_render_ids: set[str] = set()
        for structure_position, structure in enumerate(structures):
            structure_context = f"{context}.structures[{structure_position}]"
            if not isinstance(structure, dict):
                errors.append(f"{structure_context} must be an object")
                continue
            render_id = structure.get("render_id")
            route = structure.get("route")
            if not isinstance(render_id, str) or not render_id.strip():
                errors.append(f"{structure_context}.render_id must be a non-empty string")
                continue
            if render_id in seen_render_ids:
                errors.append(f"{context}: duplicate render_id {render_id}")
            seen_render_ids.add(render_id)
            if not isinstance(route, str) or not route.strip():
                errors.append(f"{structure_context}.route must be a non-empty string")
            rendered_pairs.add((candidate_id, render_id))

            _, metrics_raw = check_ref(
                root,
                structure.get("metrics"),
                f"{structure_context}.metrics",
                delivery_paths,
                errors,
            )
            site_metrics = structure.get("site_metrics")
            if (
                not isinstance(site_metrics, list)
                or not site_metrics
                or any(
                    not isinstance(metric, dict)
                    or not isinstance(metric.get("name"), str)
                    or not metric["name"].strip()
                    or not isinstance(metric.get("source"), str)
                    or not metric["source"].strip()
                    or not isinstance(metric.get("metric_id"), str)
                    or not metric["metric_id"].strip()
                    or not isinstance(metric.get("unit"), str)
                    or not metric["unit"].strip()
                    or metric.get("state") != "measured"
                    or metric.get("scope") != "target-site"
                    or not finite_numeric(metric.get("value"))
                    for metric in site_metrics
                )
            ):
                errors.append(
                    f"{structure_context}.site_metrics must contain at least one named, sourced "
                    "site-aware metric with a finite numeric value"
                )
            metric_text = parser.site_metric_text.get(render_id, "").strip()
            if not metric_text:
                errors.append(
                    f"{structure_context}: HTML must show site-aware metrics in "
                    f'data-site-metrics="{render_id}"'
                )
            elif isinstance(site_metrics, list):
                for metric in site_metrics:
                    if isinstance(metric, dict) and (
                        str(metric.get("metric_id")) not in metric_text
                        or str(metric.get("value")) not in metric_text
                    ):
                        errors.append(
                            f"{structure_context}: HTML site metrics must show metric_id and value"
                        )
            if metrics_raw is not None:
                try:
                    metrics_payload = strict_json.loads(metrics_raw)
                except strict_json.StrictJSONError as exc:
                    errors.append(f"{structure_context}.metrics is not strict JSON: {exc}")
                else:
                    if not isinstance(metrics_payload, dict):
                        errors.append(f"{structure_context}.metrics must contain a JSON object")
                    elif (
                        metrics_payload.get("schema_version") != "codex-binder-site-metrics/v1"
                        or metrics_payload.get("candidate_id") != candidate_id
                        or metrics_payload.get("render_id") != render_id
                        or metrics_payload.get("metrics") != site_metrics
                    ):
                        errors.append(
                            f"{structure_context}.metrics must bind the candidate, render, and exact site_metrics"
                        )

            visual = structure.get("visual_context")
            if not isinstance(visual, dict):
                errors.append(f"{structure_context}.visual_context must be an object")
                visual = {}
            if visual.get("view_kind") != "binder-on-target-site":
                errors.append(
                    f"{structure_context}.visual_context.view_kind must be binder-on-target-site"
                )
            if visual.get("target_chains") != target_chains:
                errors.append(
                    f"{structure_context}.visual_context.target_chains must match scientific_context.target_chains"
                )
            binder_chains = visual.get("binder_chains")
            if (
                not isinstance(binder_chains, list)
                or not binder_chains
                or any(not isinstance(value, str) or not value.strip() for value in binder_chains)
                or len(set(binder_chains)) != len(binder_chains)
            ):
                errors.append(
                    f"{structure_context}.visual_context.binder_chains must be a non-empty unique string array"
                )
                binder_chains = []
            if set(binder_chains).intersection(target_chains):
                errors.append(f"{structure_context}.visual_context binder and target chains must differ")
            if visual.get("site_residues") != site_residues:
                errors.append(
                    f"{structure_context}.visual_context.site_residues must match scientific_context.site_residues"
                )
            for field in ("target_visible", "binder_visible", "site_highlighted"):
                if visual.get(field) is not True:
                    errors.append(f"{structure_context}.visual_context.{field} must be true")
            if visual.get("background") != "white":
                errors.append(f"{structure_context}.visual_context.background must be white")
            for field in ("renderer", "renderer_version"):
                value = visual.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{structure_context}.visual_context.{field} must be a non-empty string")
            _, render_recipe_raw = check_ref(
                root,
                visual.get("render_recipe"),
                f"{structure_context}.visual_context.render_recipe",
                delivery_paths,
                errors,
            )
            coordinate_path, coordinate_raw = check_ref(
                root,
                structure.get("coordinates"),
                f"{structure_context}.coordinates",
                delivery_paths,
                errors,
            )
            coordinate_suffix = Path(coordinate_path).suffix.lower() if coordinate_path else ""
            if coordinate_path and coordinate_suffix not in {".cif", ".mmcif", ".pdb"}:
                errors.append(f"{structure_context}: coordinates must be PDB or mmCIF")
            elif coordinate_raw is not None:
                check_coordinate_content(
                    coordinate_raw,
                    coordinate_suffix,
                    target_chains,
                    binder_chains,
                    site_residues,
                    structure_context,
                    errors,
                )
            render_path, render_raw = check_ref(
                root,
                structure.get("render"),
                f"{structure_context}.render",
                delivery_paths,
                errors,
            )
            if render_path and render_raw is not None and not valid_image(render_raw, Path(render_path).suffix):
                errors.append(f"{structure_context}: render is not a validated image")
            elif render_path and render_raw is not None:
                dimensions = image_dimensions(root / render_path, render_raw)
                if dimensions is None or dimensions[0] < 640 or dimensions[1] < 480:
                    errors.append(f"{structure_context}: render must be at least 640x480 pixels")
            else:
                dimensions = None
            render_ref = structure.get("render")
            if isinstance(render_ref, dict) and isinstance(render_ref.get("sha256"), str):
                render_sha256_by_pair[(candidate_id, render_id)] = render_ref["sha256"]
            if render_recipe_raw is not None:
                try:
                    recipe = strict_json.loads(render_recipe_raw)
                except strict_json.StrictJSONError as exc:
                    errors.append(f"{structure_context}.visual_context.render_recipe is not strict JSON: {exc}")
                else:
                    coordinate_ref = structure.get("coordinates")
                    render_ref = structure.get("render")
                    expected_recipe = {
                        "schema_version": "codex-binder-render-recipe/v1",
                        "candidate_id": candidate_id,
                        "render_id": render_id,
                        "coordinates_sha256": coordinate_ref.get("sha256") if isinstance(coordinate_ref, dict) else None,
                        "render_sha256": render_ref.get("sha256") if isinstance(render_ref, dict) else None,
                        "target_chains": target_chains,
                        "binder_chains": binder_chains,
                        "site_residues": site_residues,
                        "background": "white",
                        "renderer": visual.get("renderer"),
                        "renderer_version": visual.get("renderer_version"),
                        "width": dimensions[0] if dimensions else None,
                        "height": dimensions[1] if dimensions else None,
                    }
                    if not isinstance(recipe, dict) or any(
                        recipe.get(field) != expected
                        for field, expected in expected_recipe.items()
                    ):
                        errors.append(
                            f"{structure_context}.visual_context.render_recipe must bind coordinates, render, chains, site, renderer, and dimensions"
                        )
            image_record = parser.structure_images.get(render_id, {})
            image_path = resolve_html_path(report_path, image_record.get("src")) if report_path else None
            if render_path and image_path != render_path:
                errors.append(
                    f"{structure_context}: HTML must show the render with "
                    f'data-structure-render="{render_id}"'
                )
            expected_site = ",".join(site_residues)
            expected_image_fields = {
                "data-target-chains": ",".join(target_chains),
                "data-binder-chains": ",".join(binder_chains),
                "data-target-site": expected_site,
                "data-site-highlighted": "true",
                "data-background": "white",
            }
            for field, expected in expected_image_fields.items():
                if image_record.get(field) != expected:
                    errors.append(
                        f'{structure_context}: HTML image {render_id!r} requires {field}="{expected}"'
                    )
            caption = " ".join(parser.structure_captions.get(render_id, "").split())
            required_caption_terms = [
                candidate_id,
                str(scientific_context.get("target_id", "")),
                "binder",
                "target",
                "site",
                *site_residues,
            ]
            if not caption or any(term.casefold() not in caption.casefold() for term in required_caption_terms):
                errors.append(
                    f"{structure_context}: HTML must show a caption with "
                    f'data-structure-caption="{render_id}" naming the binder, target, and locked site residues'
                )
            link_path = resolve_html_path(report_path, parser.structure_links.get(render_id)) if report_path else None
            if coordinate_path and link_path != coordinate_path:
                errors.append(
                    f"{structure_context}: HTML must link coordinates with "
                    f'data-structure-download="{render_id}"'
                )

    if set(sequence_candidate_ids) != seen_candidates:
        errors.append("candidate_scope.sequence_candidate_ids must exactly match candidate records")

    captured_pairs = set(browser_capture_pairs)
    for candidate_id, render_id in sorted(captured_pairs - rendered_pairs):
        errors.append(
            "browser verification capture does not match a delivered candidate render: "
            f"candidate {candidate_id}, render {render_id}"
        )
    for candidate_id, render_id in sorted(rendered_pairs - captured_pairs):
        errors.append(
            "browser verification is missing a capture for delivered candidate render: "
            f"candidate {candidate_id}, render {render_id}"
        )

    video = index.get("video")
    if not isinstance(video, dict):
        errors.append("video must be an object")
        video = {}
    storyboard = video.get("storyboard")
    storyboard_raw: bytes | None = None
    if storyboard is not None:
        _, storyboard_raw = check_ref(
            root,
            storyboard,
            "video.storyboard",
            delivery_paths,
            errors,
        )
    rendered_video = video.get("render")
    if requirements.get("video") in REQUIRED_POSTURES and rendered_video is None:
        errors.append("required video is missing; a storyboard does not satisfy this requirement")
    if rendered_video is not None:
        video_path, video_raw = check_ref(
            root,
            rendered_video,
            "video.render",
            delivery_paths,
            errors,
            load_content=False,
        )
        if (
            video_path
            and video_raw is not None
            and not valid_video(root / video_path, Path(video_path).suffix)
        ):
            errors.append("video.render is not a validated MP4/WebM file")
        if storyboard is None:
            errors.append(
                "video.render requires video.storyboard with candidate/render-bound scenes"
            )
        storyboard_scene_ids: set[str] = set()
        if storyboard_raw is not None:
            try:
                storyboard_payload = strict_json.loads(storyboard_raw)
            except strict_json.StrictJSONError as exc:
                errors.append(f"video.storyboard is not strict JSON: {exc}")
            else:
                video_ref = rendered_video if isinstance(rendered_video, dict) else {}
                if (
                    not isinstance(storyboard_payload, dict)
                    or storyboard_payload.get("schema_version")
                    != "codex-binder-video-storyboard/v1"
                    or storyboard_payload.get("video_sha256") != video_ref.get("sha256")
                ):
                    errors.append(
                        "video.storyboard must bind the rendered video SHA-256 with schema codex-binder-video-storyboard/v1"
                    )
                scenes = (
                    storyboard_payload.get("scenes")
                    if isinstance(storyboard_payload, dict)
                    else None
                )
                if not isinstance(scenes, list) or not scenes:
                    errors.append("video.storyboard.scenes must be a non-empty array")
                else:
                    for position, scene in enumerate(scenes):
                        context = f"video.storyboard.scenes[{position}]"
                        if not isinstance(scene, dict):
                            errors.append(f"{context} must be an object")
                            continue
                        scene_id = scene.get("scene_id")
                        candidate_id = scene.get("candidate_id")
                        render_id = scene.get("render_id")
                        if not isinstance(scene_id, str) or not scene_id.strip():
                            errors.append(f"{context}.scene_id must be a non-empty string")
                        elif scene_id in storyboard_scene_ids:
                            errors.append(f"video.storyboard contains duplicate scene_id: {scene_id}")
                        else:
                            storyboard_scene_ids.add(scene_id)
                        if not isinstance(candidate_id, str) or not candidate_id.strip():
                            errors.append(f"{context}.candidate_id must be a non-empty string")
                        if not isinstance(render_id, str) or not render_id.strip():
                            errors.append(f"{context}.render_id must be a non-empty string")
                        pair = (candidate_id, render_id)
                        if pair not in rendered_pairs:
                            errors.append(
                                f"{context} must bind a delivered candidate/render pair"
                            )
                        elif scene.get("render_sha256") != render_sha256_by_pair.get(pair):
                            errors.append(
                                f"{context}.render_sha256 must match the bound render"
                            )
                        start_seconds = scene.get("start_seconds")
                        end_seconds = scene.get("end_seconds")
                        if (
                            isinstance(start_seconds, bool)
                            or isinstance(end_seconds, bool)
                            or not isinstance(start_seconds, (int, float))
                            or not isinstance(end_seconds, (int, float))
                            or start_seconds < 0
                            or end_seconds <= start_seconds
                        ):
                            errors.append(
                                f"{context} requires non-negative start_seconds before end_seconds"
                            )

        linked_videos = (
            [
                record
                for record in parser.videos
                if resolve_html_path(report_path, record.get("src")) == video_path
            ]
            if report_path and video_path
            else []
        )
        if not linked_videos:
            errors.append("HTML must embed the rendered video with data-campaign-video")
        elif not any(record.get("controls") is True for record in linked_videos):
            errors.append("HTML video with data-campaign-video must expose browser controls")
        elif storyboard_scene_ids:
            def scene_ids(record: dict[str, Any]) -> set[str]:
                raw_ids = record.get("scene_ids")
                if not isinstance(raw_ids, str):
                    return set()
                return {value.strip() for value in raw_ids.split(",") if value.strip()}

            if not any(
                record.get("controls") is True
                and scene_ids(record) == storyboard_scene_ids
                for record in linked_videos
            ):
                errors.append(
                    "HTML video must declare data-video-scenes matching the storyboard scene IDs"
                )
        if isinstance(checked_sections, list) and "video-playback" not in checked_sections:
            errors.append("browser verification must include video-playback when a video is delivered")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="campaign delivery root")
    parser.add_argument("--index", default="delivery-index.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not safe_relative_path(args.index):
        errors, warnings = [f"delivery index has an invalid relative path: {args.index!r}"], []
    else:
        index_path = args.root / args.index
        try:
            payload = strict_json.loads(index_path.read_bytes())
        except (OSError, strict_json.StrictJSONError) as exc:
            errors, warnings = [f"cannot read delivery index: {exc}"], []
        else:
            errors, warnings = validate(payload, args.root, args.index)
    result = {"ok": not errors, "errors": errors, "warnings": warnings}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("PASS" if not errors else "FAIL")
        for message in errors:
            print(f"ERROR: {message}")
        for message in warnings:
            print(f"WARNING: {message}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
