#!/usr/bin/env python3
"""Verify a Codex Binder Lane public release tree and receipt."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_PATH = "public-export-receipt.json"
PLUGIN_ROOT = Path("plugins/codex-binder-lane")
GENERATED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
GENERATED_FILE_NAMES = {".coverage", ".DS_Store"}
GENERATED_SUFFIXES = {".pyc", ".pyo"}
ALLOWED_CLASSIFICATIONS = {
    "plugin-metadata",
    "plugin-source",
    "public-documentation",
    "public-media",
    "public-template",
    "synthetic-canary-declaration",
}
LOCKED_PUBLIC_MEDIA = {
    "docs/media/binder-lane-banner.jpg": {
        "format": "jpeg",
        "height": 640,
        "source": "docs/media/binder-lane-banner.jpg",
        "sha256": "fd0be20b81dcb9e9a7cdf4b3432040dbb3f08bf27ced6469720c9b936b0dfa8a",
        "size_bytes": 277959,
        "width": 1280,
    },
    "plugins/codex-binder-lane/assets/icon.png": {
        "format": "png",
        "height": 256,
        "source": "assets/icon.png",
        "sha256": "57de3d7be97280eedcf0c39d671b42318b9d0c2ec10ac5bf986851f3a0815be5",
        "size_bytes": 69972,
        "width": 256,
    },
    "plugins/codex-binder-lane/assets/logo.png": {
        "format": "png",
        "height": 1024,
        "source": "assets/logo.png",
        "sha256": "c60ca5acc9a8ba535bbe4418019178998b33a5ccbec4af0d7533cc8394d6d341",
        "size_bytes": 637163,
        "width": 1024,
    }
}
RAW_BIOLOGY_SUFFIXES = {
    ".a3m",
    ".cif",
    ".fa",
    ".faa",
    ".fasta",
    ".fastq",
    ".fna",
    ".mmcif",
    ".pdb",
    ".sdf",
}
POSIX_SEPARATOR = "/"
WINDOWS_SEPARATOR = chr(92)
PERSONAL_HOME_RE = re.compile(
    rf"(?i)(?:^|[\s\"'(]){re.escape(POSIX_SEPARATOR)}(?:Users|home)"
    rf"{re.escape(POSIX_SEPARATOR)}[^{re.escape(POSIX_SEPARATOR)}\s]+"
    rf"(?:{re.escape(POSIX_SEPARATOR)}|$)"
)
WINDOWS_HOME_RE = re.compile(
    rf"(?i)\b[A-Z]:{re.escape(WINDOWS_SEPARATOR)}Users"
    rf"{re.escape(WINDOWS_SEPARATOR)}[^{re.escape(WINDOWS_SEPARATOR)}\s]+"
)
WORKSPACE_DIRECTORY_RE = re.compile(r"(?i)\bgithub_[0-9]+\b")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(ValueError):
    pass


def strict_json_loads(value: str) -> Any:
    def reject_constant(constant: str) -> None:
        raise VerificationError(f"non-finite JSON number is forbidden: {constant}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise VerificationError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    try:
        return json.loads(
            value,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise VerificationError(str(exc)) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def allowlist_digest(records: list[dict[str, Any]]) -> str:
    metadata = [
        {
            "biology_classification": record.get("biology_classification"),
            "classification": record.get("classification"),
            "path": record.get("path"),
            "source": record.get("source"),
        }
        for record in records
    ]
    canonical = json.dumps(
        metadata,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise VerificationError(f"unsafe receipt path: {value!r}")
    if re.match(r"(?i)^[A-Z]:", value):
        raise VerificationError(f"unsafe receipt path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise VerificationError(f"unsafe receipt path: {value!r}")
    return path.as_posix()


def generated_path(relative_path: Path) -> bool:
    return (
        any(part in GENERATED_DIRECTORY_NAMES for part in relative_path.parts)
        or relative_path.name in GENERATED_FILE_NAMES
        or relative_path.suffix in GENERATED_SUFFIXES
    )


def regular_file(root: Path, relative_path: str) -> Path:
    current = root
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise VerificationError(f"symlink is forbidden: {relative_path}")
    if not current.is_file():
        raise VerificationError(f"receipt file is missing or irregular: {relative_path}")
    return current


def read_json(path: Path) -> Any:
    try:
        return strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, VerificationError) as exc:
        raise VerificationError(f"cannot read JSON file {path.name}: {exc}") from exc


def verify_record_metadata(record: dict[str, Any], relative_path: str, path: Path) -> None:
    classification = record.get("classification")
    biology = record.get("biology_classification")
    source = record.get("source")
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise VerificationError(f"unsupported classification: {relative_path}")
    if classification == "synthetic-canary-declaration":
        if relative_path != "synthetic-canary.json" or biology != "synthetic-non-biological" or source is not None:
            raise VerificationError("synthetic canary record mismatch")
    else:
        if biology != "none" or source is None:
            raise VerificationError(f"release classification mismatch: {relative_path}")
        safe_relative_path(source)
    if classification == "public-media":
        expected = LOCKED_PUBLIC_MEDIA.get(relative_path)
        if expected is None or source != expected["source"]:
            raise VerificationError(f"unapproved public media: {relative_path}")
        data = path.read_bytes()
        if len(data) != expected["size_bytes"] or sha256_file(path) != expected["sha256"]:
            raise VerificationError(f"locked public media changed: {relative_path}")
        if expected["format"] == "jpeg":
            if not data.startswith(b"\xff\xd8\xff\xe0") or not data.endswith(b"\xff\xd9"):
                raise VerificationError(f"locked public media is not the reviewed JPEG: {relative_path}")
        elif expected["format"] == "png":
            if (
                not data.startswith(b"\x89PNG\r\n\x1a\n")
                or data[12:16] != b"IHDR"
                or int.from_bytes(data[16:20], "big") != expected["width"]
                or int.from_bytes(data[20:24], "big") != expected["height"]
                or data[25] != 6
            ):
                raise VerificationError(f"locked public media is not the reviewed RGBA PNG: {relative_path}")
        else:
            raise VerificationError(f"unsupported locked media format: {relative_path}")
        if b"Exif\x00\x00" in data or b"http://" in data or b"https://" in data:
            raise VerificationError(f"locked public media contains forbidden metadata: {relative_path}")
        return
    if PurePosixPath(relative_path).suffix.lower() in RAW_BIOLOGY_SUFFIXES:
        raise VerificationError(f"raw biology file is forbidden: {relative_path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise VerificationError(f"release file is not UTF-8 text: {relative_path}") from exc
    if any(
        pattern.search(text)
        for pattern in (PERSONAL_HOME_RE, WINDOWS_HOME_RE, WORKSPACE_DIRECTORY_RE)
    ):
        raise VerificationError(f"machine-specific release metadata: {relative_path}")


def verify_receipt(root: Path) -> tuple[int, dict[str, Any], dict[str, Any]]:
    receipt_file = regular_file(root, RECEIPT_PATH)
    receipt = read_json(receipt_file)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "codex-binder-public-export-receipt/v1":
        raise VerificationError("unsupported public export receipt")
    if receipt.get("source_root") != ".":
        raise VerificationError("receipt source_root must be '.'")
    allowlist_sha256 = receipt.get("allowlist_sha256")
    if not isinstance(allowlist_sha256, str) or SHA256_RE.fullmatch(allowlist_sha256) is None:
        raise VerificationError("receipt allowlist_sha256 must be a lowercase SHA-256")
    records = receipt.get("files")
    if not isinstance(records, list) or not records:
        raise VerificationError("receipt must contain file records")

    paths: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise VerificationError(f"receipt record {index} must be an object")
        relative_path = safe_relative_path(record.get("path"))
        paths.append(relative_path)
        path = regular_file(root, relative_path)
        verify_record_metadata(record, relative_path, path)
        if record.get("size_bytes") != path.stat().st_size:
            raise VerificationError(f"byte count mismatch: {relative_path}")
        if record.get("sha256") != sha256_file(path):
            raise VerificationError(f"SHA-256 mismatch: {relative_path}")

    if paths != sorted(paths):
        raise VerificationError("receipt paths are not sorted")
    if len(paths) != len(set(paths)):
        raise VerificationError("receipt contains duplicate paths")
    if allowlist_sha256 != allowlist_digest(records):
        raise VerificationError("receipt allowlist_sha256 does not match file metadata")

    actual: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if generated_path(relative):
            continue
        if path.is_symlink():
            raise VerificationError(f"symlink is forbidden: {relative.as_posix()}")
        if path.is_file() and relative.as_posix() != RECEIPT_PATH:
            actual.add(relative.as_posix())
    expected = set(paths)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise VerificationError(f"release file set mismatch: missing={missing}, extra={extra}")

    plugin = read_json(root / PLUGIN_ROOT / ".codex-plugin/plugin.json")
    marketplace = read_json(root / ".agents/plugins/marketplace.json")
    return len(paths), plugin, marketplace


def verify_metadata(plugin: Any, marketplace: Any) -> tuple[str, str]:
    if not isinstance(plugin, dict):
        raise VerificationError("plugin manifest must be an object")
    name = plugin.get("name")
    version = plugin.get("version")
    if name != "codex-binder-lane":
        raise VerificationError("plugin name mismatch")
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        raise VerificationError("plugin version is not semantic versioning")
    if plugin.get("license") != "Apache-2.0":
        raise VerificationError("plugin license mismatch")

    if not isinstance(marketplace, dict) or marketplace.get("name") != "codex-binder-lane":
        raise VerificationError("marketplace name mismatch")
    entries = marketplace.get("plugins")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise VerificationError("marketplace must contain one plugin entry")
    entry = entries[0]
    expected_source = {"source": "local", "path": "./plugins/codex-binder-lane"}
    expected_policy = {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
    if entry.get("name") != name or entry.get("source") != expected_source:
        raise VerificationError("marketplace source does not match the plugin")
    if entry.get("policy") != expected_policy or entry.get("category") != "Scientific Research":
        raise VerificationError("marketplace policy or category mismatch")
    return name, version


def main() -> int:
    try:
        count, plugin, marketplace = verify_receipt(REPO_ROOT)
        name, version = verify_metadata(plugin, marketplace)
    except VerificationError as exc:
        print(f"verify_public_export: {exc}", file=sys.stderr)
        return 2
    print(f"verified self-consistency of {count} receipt files for {name} {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
