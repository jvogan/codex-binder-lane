#!/usr/bin/env python3
"""Validate one immutable Binder Lane target/site lock with read-only local checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import ipaddress
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import strict_json  # noqa: E402


SCHEMA_VERSION = "codex-binder-target-site-lock/v1"
ALLOWED_CONFIDENTIALITY = {"public", "private", "restricted"}
ALLOWED_CLAIM_CEILINGS = {"plan-only", "transport-proven"}
ALLOWED_CHAIN_ROLES = {"target", "binder", "context", "partner"}
ALLOWED_SITE_MODES = {
    "explicit-residues",
    "reference-interface",
    "pose-derived",
    "spatial-patch",
}
AMBIGUOUS_TEXT = {"", "n/a", "na", "none", "null", "tbd", "unknown", "unspecified"}
IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CHAIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
AUTHOR_NUMBER_RE = re.compile(r"^-?[0-9]+$")
INSERTION_CODE_RE = re.compile(r"^[A-Z0-9]$")
URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>'\"]+", re.IGNORECASE)
PATH_SLASH = chr(47)
POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._~-])" + PATH_SLASH + r"(?!" + PATH_SLASH + r")[^\s<>'\"]+"
)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s<>'\"]+"
)
HOME_PATH_RE = re.compile(r"(?<![A-Za-z0-9._~-])~[^\s/\\]*[/\\][^\s<>'\"]*")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|credential)\b\s*[:=]\s*\S+"
)
SECRET_PREFIX_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{10,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bAKIA[A-Z0-9]{16}\b)"
)
SECRET_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "client_secret",
    "credential",
    "key",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}
IDENTITY_REQUIREMENT = (
    "must start with a letter or digit and use only letters, digits, '.', '_', ':', or '-'"
)

ROOT_REQUIRED = {
    "schema_version",
    "campaign_id",
    "target_id",
    "confidentiality",
    "source_lock",
    "primary_input",
    "chains",
    "residue_map",
    "site",
    "claim_ceiling",
}
ROOT_OPTIONAL = {"fixture_kind", "non_biological"}
SOURCE_LOCK_FIELDS = {
    "source_id",
    "source_version",
    "source_sha256",
    "source_size_bytes",
    "input_sha256",
    "input_size_bytes",
}
ARTIFACT_REF_FIELDS = {"path", "sha256", "size_bytes"}
CHAIN_FIELDS = {"source_chain_id", "campaign_chain_id", "role"}
SITE_FIELDS = {"site_id", "mode", "numbering_scheme", "residues", "evidence"}
RESIDUE_REQUIRED = {
    "campaign_chain_id",
    "campaign_residue_number",
    "author_residue_number",
    "insertion_code",
}
RESIDUE_OPTIONAL = {"evidence"}
RESIDUE_MAP_REQUIRED_FIELDS = {
    "source_chain_id",
    "author_residue_number",
    "insertion_code",
    "campaign_chain_id",
    "campaign_residue_number",
}
RESIDUE_MAP_OPTIONAL_FIELDS = {"residue_name", "meaning"}
MAX_LOCK_BYTES = 2 * 1024 * 1024
MAX_PRIMARY_INPUT_BYTES = 512 * 1024 * 1024
MAX_RESIDUE_MAP_BYTES = 16 * 1024 * 1024


def _is_nonnegative_integer(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value > 0 if positive else value >= 0


def _is_identity(value: Any, pattern: re.Pattern[str] = IDENTITY_RE) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _is_unambiguous_text(value: Any) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    if value.lower() in AMBIGUOUS_TEXT:
        return False
    return not any(ord(character) < 32 for character in value)


def _private_or_local_host(hostname: str | None) -> bool:
    if not hostname:
        return True
    host = hostname.lower().rstrip(".")
    if (
        host in {"localhost", "localhost.localdomain"}
        or "." not in host
        or host.endswith((".internal", ".invalid", ".lan", ".local", ".localhost", ".test"))
    ):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    return False


def _query_contains_credential(query: str) -> bool:
    for key, _ in parse_qsl(query, keep_blank_values=True):
        normalized = key.lower().replace("-", "_")
        if normalized in SECRET_QUERY_KEYS or normalized.endswith(
            ("_api_key", "_credential", "_password", "_secret", "_signature", "_token")
        ):
            return True
    return False


def _portable_text_findings(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            findings.extend(_portable_text_findings(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_portable_text_findings(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if SECRET_ASSIGNMENT_RE.search(value) or SECRET_PREFIX_RE.search(value):
            findings.append(f"{path} contains credential material; remove the value")
        uri_matches = list(URI_RE.finditer(value))
        for match in uri_matches:
            uri = match.group(0).rstrip(".,);]")
            try:
                parsed = urlsplit(uri)
                hostname = parsed.hostname
            except ValueError:
                findings.append(f"{path} contains an invalid URI; remove or replace it")
                continue
            scheme = parsed.scheme.lower()
            if scheme == "file":
                findings.append(f"{path} contains a local file URL; use a portable artifact reference")
            elif scheme not in {"http", "https"}:
                findings.append(f"{path} contains a non-HTTP URI; use a portable artifact reference")
            elif not parsed.netloc or hostname is None:
                findings.append(f"{path} contains an invalid HTTP URL; remove or replace it")
            elif parsed.username or parsed.password or _query_contains_credential(parsed.query):
                findings.append(f"{path} contains a credential-bearing URL; remove the credential")
            elif _private_or_local_host(hostname):
                findings.append(f"{path} contains a private or local endpoint; record public provenance only")
        masked = value
        for match in reversed(uri_matches):
            masked = masked[: match.start()] + (" " * (match.end() - match.start())) + masked[match.end() :]
        if POSIX_ABSOLUTE_PATH_RE.search(masked):
            findings.append(f"{path} contains an absolute POSIX path; use a portable artifact reference")
        if WINDOWS_ABSOLUTE_PATH_RE.search(masked):
            findings.append(f"{path} contains an absolute Windows path; use a portable artifact reference")
        if HOME_PATH_RE.search(masked):
            findings.append(f"{path} contains a home-relative path; use a portable artifact reference")
    return findings


def _validate_residue_map_csv(
    data: bytes,
    *,
    declared_chain_pairs: set[tuple[str, str]],
    site_mappings: list[tuple[str, tuple[str, str, str | None, str, int]]],
    errors: list[str],
) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("residue_map must contain valid UTF-8 CSV")
        return
    if any(
        (ord(character) < 32 and character not in {"\n", "\r"}) or ord(character) == 127
        for character in text
    ):
        errors.append("residue_map CSV contains a control character")
        return
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error:
        errors.append("residue_map must contain well-formed CSV")
        return
    if not rows:
        errors.append("residue_map CSV must contain a header and at least one data row")
        return

    header = rows[0]
    if not header or any(not field or field != field.strip() for field in header):
        errors.append("residue_map header must use non-empty canonical field names")
        return
    if len(header) != len(set(header)):
        errors.append("residue_map header contains duplicate fields")
        return
    missing = sorted(RESIDUE_MAP_REQUIRED_FIELDS - set(header))
    unknown = set(header) - RESIDUE_MAP_REQUIRED_FIELDS - RESIDUE_MAP_OPTIONAL_FIELDS
    if missing:
        errors.append(f"residue_map header is missing required fields: {', '.join(missing)}")
    if unknown:
        noun = "field" if len(unknown) == 1 else "fields"
        errors.append(f"residue_map header contains {len(unknown)} unknown {noun}")
    if missing or unknown:
        return

    map_mappings: set[tuple[str, str, str | None, str, int]] = set()
    campaign_keys: set[tuple[str, int]] = set()
    author_keys: set[tuple[str, str, str | None]] = set()
    data_row_count = 0
    for row_number, row in enumerate(rows[1:], start=2):
        context = f"residue_map row {row_number}"
        if not row or all(cell == "" for cell in row):
            errors.append(f"{context} must contain residue mapping values")
            continue
        data_row_count += 1
        if len(row) != len(header):
            errors.append(f"{context} must contain exactly {len(header)} fields")
            continue
        record = dict(zip(header, row, strict=True))
        if any(cell != cell.strip() for cell in row):
            errors.append(f"{context} contains leading or trailing whitespace")
            continue

        source_chain = record["source_chain_id"]
        author_number = record["author_residue_number"]
        insertion_value = record["insertion_code"]
        campaign_chain = record["campaign_chain_id"]
        campaign_number_value = record["campaign_residue_number"]
        row_valid = True
        if not _is_identity(source_chain, CHAIN_RE):
            errors.append(f"{context}.source_chain_id must be an explicit chain identity")
            row_valid = False
        if AUTHOR_NUMBER_RE.fullmatch(author_number) is None:
            errors.append(f"{context}.author_residue_number must be an integer string")
            row_valid = False
        insertion_code: str | None = insertion_value or None
        if insertion_code is not None and INSERTION_CODE_RE.fullmatch(insertion_code) is None:
            errors.append(
                f"{context}.insertion_code must be empty or one uppercase alphanumeric character"
            )
            row_valid = False
        if not _is_identity(campaign_chain, CHAIN_RE):
            errors.append(f"{context}.campaign_chain_id must be an explicit chain identity")
            row_valid = False
        if re.fullmatch(r"[1-9][0-9]*", campaign_number_value) is None:
            errors.append(f"{context}.campaign_residue_number must be a positive whole number")
            row_valid = False
            campaign_number = 0
        else:
            campaign_number = int(campaign_number_value)

        for field in sorted(RESIDUE_MAP_OPTIONAL_FIELDS & set(header)):
            if not _is_unambiguous_text(record[field]):
                errors.append(f"{context}.{field} must be explicit and non-placeholder text")
                row_valid = False

        if not row_valid:
            continue
        chain_pair = source_chain, campaign_chain
        if chain_pair not in declared_chain_pairs:
            errors.append(f"{context} uses a chain pair that target lock chains do not declare")
        campaign_key = campaign_chain, campaign_number
        if campaign_key in campaign_keys:
            errors.append(f"{context} duplicates a campaign residue mapping")
        campaign_keys.add(campaign_key)
        author_key = source_chain, author_number, insertion_code
        if author_key in author_keys:
            errors.append(f"{context} duplicates an author residue mapping")
        author_keys.add(author_key)
        map_mappings.add(
            (source_chain, author_number, insertion_code, campaign_chain, campaign_number)
        )

    if data_row_count == 0:
        errors.append("residue_map CSV must contain at least one data row")
    for context, mapping in site_mappings:
        if mapping not in map_mappings:
            errors.append(f"{context} has no exact residue_map row")


def _check_object(
    value: Any,
    *,
    required: set[str],
    optional: set[str] | None,
    context: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return None
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        errors.append(f"{context} is missing required fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"{context} contains unknown fields: {', '.join(unknown)}")
    return value


def _safe_relative_path(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _read_relative_regular(
    root: Path,
    relative_path: str,
    context: str,
    errors: list[str],
    *,
    maximum_bytes: int,
) -> bytes | None:
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        errors.append(f"{context}: cannot inspect artifact root: {exc}")
        return None
    if stat.S_ISLNK(root_mode):
        errors.append(f"{context}: artifact root must not be a symlink")
        return None
    if not stat.S_ISDIR(root_mode):
        errors.append(f"{context}: artifact root must be a directory")
        return None

    current = root
    parts = PurePosixPath(relative_path).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            errors.append(f"{context}: referenced file is missing: {relative_path}")
            return None
        except OSError as exc:
            errors.append(f"{context}: cannot inspect {relative_path}: {exc}")
            return None
        if stat.S_ISLNK(mode):
            errors.append(f"{context}: symlinked artifact paths are forbidden: {relative_path}")
            return None
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            errors.append(f"{context}: artifact path component is not a directory: {relative_path}")
            return None
        if index == len(parts) - 1 and not stat.S_ISREG(mode):
            errors.append(f"{context}: artifact must be a regular file: {relative_path}")
            return None

    descriptor = -1
    try:
        descriptor = os.open(current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            errors.append(f"{context}: artifact must be a regular file: {relative_path}")
            return None
        if opened.st_size > maximum_bytes:
            errors.append(f"{context}: artifact exceeds the {maximum_bytes}-byte limit")
            return None
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read(maximum_bytes + 1)
        if len(data) > maximum_bytes:
            errors.append(f"{context}: artifact exceeds the {maximum_bytes}-byte limit")
            return None
        return data
    except OSError as exc:
        errors.append(f"{context}: cannot read {relative_path}: {exc}")
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _check_artifact_ref(
    value: Any,
    *,
    context: str,
    root: Path | None,
    errors: list[str],
    maximum_bytes: int,
) -> tuple[str, str, int, bytes | None] | None:
    ref = _check_object(
        value,
        required=ARTIFACT_REF_FIELDS,
        optional=None,
        context=context,
        errors=errors,
    )
    if ref is None:
        return None
    path = ref.get("path")
    digest = ref.get("sha256")
    size_bytes = ref.get("size_bytes")
    valid = True
    if not _safe_relative_path(path):
        errors.append(f"{context}.path must be a safe relative POSIX path")
        valid = False
    if not _is_sha256(digest):
        errors.append(f"{context}.sha256 must be a lowercase SHA-256")
        valid = False
    if not _is_nonnegative_integer(size_bytes, positive=True):
        errors.append(f"{context}.size_bytes must be a positive whole number")
        valid = False
    elif size_bytes > maximum_bytes:
        errors.append(f"{context}.size_bytes exceeds the {maximum_bytes}-byte limit")
        valid = False
    if not valid:
        return None

    data: bytes | None = None
    if root is not None:
        data = _read_relative_regular(
            root,
            path,
            context,
            errors,
            maximum_bytes=maximum_bytes,
        )
        if data is not None:
            if len(data) != size_bytes:
                errors.append(f"{context}: byte count mismatch for {path}")
            if hashlib.sha256(data).hexdigest() != digest:
                errors.append(f"{context}: SHA-256 mismatch for {path}")
    return path, digest, size_bytes, data


def validate(lock: Any, artifact_root: Path | None = None) -> list[str]:
    """Return all validation errors for one parsed target/site lock."""

    errors: list[str] = []
    root = _check_object(
        lock,
        required=ROOT_REQUIRED,
        optional=ROOT_OPTIONAL,
        context="target lock",
        errors=errors,
    )
    if root is None:
        return errors

    if root.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must equal {SCHEMA_VERSION}")
    for field in ("campaign_id", "target_id"):
        if not _is_identity(root.get(field)):
            errors.append(f"{field} {IDENTITY_REQUIREMENT}")

    fixture_kind = root.get("fixture_kind")
    non_biological = root.get("non_biological")
    if ("fixture_kind" in root) != ("non_biological" in root):
        errors.append("fixture_kind and non_biological must be declared together")
    if "fixture_kind" in root and not _is_identity(fixture_kind):
        errors.append(f"fixture_kind {IDENTITY_REQUIREMENT}")
    if "non_biological" in root and not isinstance(non_biological, bool):
        errors.append("non_biological must be a boolean")

    confidentiality = root.get("confidentiality")
    if not isinstance(confidentiality, str) or confidentiality not in ALLOWED_CONFIDENTIALITY:
        errors.append(
            f"confidentiality must be one of {sorted(ALLOWED_CONFIDENTIALITY)}"
        )
    claim_ceiling = root.get("claim_ceiling")
    if not isinstance(claim_ceiling, str) or claim_ceiling not in ALLOWED_CLAIM_CEILINGS:
        errors.append(
            "claim_ceiling on a target/site input lock may only be plan-only or transport-proven"
        )

    source_lock = _check_object(
        root.get("source_lock"),
        required=SOURCE_LOCK_FIELDS,
        optional=None,
        context="source_lock",
        errors=errors,
    )
    normalized_input_values: tuple[str, int] | None = None
    if source_lock is not None:
        for field in ("source_id", "source_version"):
            if not _is_identity(source_lock.get(field)):
                errors.append(f"source_lock.{field} {IDENTITY_REQUIREMENT}")
        source_sha256 = source_lock.get("source_sha256")
        input_sha256 = source_lock.get("input_sha256")
        source_size = source_lock.get("source_size_bytes")
        input_size = source_lock.get("input_size_bytes")
        if not _is_sha256(source_sha256):
            errors.append("source_lock.source_sha256 must be a lowercase SHA-256")
        if not _is_sha256(input_sha256):
            errors.append("source_lock.input_sha256 must be a lowercase SHA-256")
        if not _is_nonnegative_integer(source_size, positive=True):
            errors.append("source_lock.source_size_bytes must be a positive whole number")
        if not _is_nonnegative_integer(input_size, positive=True):
            errors.append("source_lock.input_size_bytes must be a positive whole number")
        if _is_sha256(input_sha256) and _is_nonnegative_integer(input_size, positive=True):
            normalized_input_values = input_sha256, input_size

    primary_input = _check_artifact_ref(
        root.get("primary_input"),
        context="primary_input",
        root=artifact_root,
        errors=errors,
        maximum_bytes=MAX_PRIMARY_INPUT_BYTES,
    )
    residue_map = _check_artifact_ref(
        root.get("residue_map"),
        context="residue_map",
        root=artifact_root,
        errors=errors,
        maximum_bytes=MAX_RESIDUE_MAP_BYTES,
    )
    if primary_input is not None and normalized_input_values is not None:
        _, input_sha256, input_size, _ = primary_input
        locked_input_sha256, locked_input_size = normalized_input_values
        if input_sha256 != locked_input_sha256 or input_size != locked_input_size:
            errors.append(
                "primary_input hash and byte count must exactly match source_lock normalized input"
            )
    if (
        primary_input is not None
        and residue_map is not None
        and primary_input[0] == residue_map[0]
    ):
        errors.append("primary_input and residue_map must reference distinct artifacts")

    chain_rows = root.get("chains")
    chain_by_campaign: dict[str, dict[str, Any]] = {}
    declared_chain_pairs: set[tuple[str, str]] = set()
    source_chain_ids: set[str] = set()
    target_chain_ids: set[str] = set()
    if not isinstance(chain_rows, list) or not chain_rows:
        errors.append("chains must be a non-empty array")
    else:
        for index, value in enumerate(chain_rows):
            context = f"chains[{index}]"
            row = _check_object(
                value,
                required=CHAIN_FIELDS,
                optional=None,
                context=context,
                errors=errors,
            )
            if row is None:
                continue
            source_chain = row.get("source_chain_id")
            campaign_chain = row.get("campaign_chain_id")
            role = row.get("role")
            if not _is_identity(source_chain, CHAIN_RE):
                errors.append(f"{context}.source_chain_id must be an explicit chain identity")
            if not _is_identity(campaign_chain, CHAIN_RE):
                errors.append(f"{context}.campaign_chain_id must be an explicit chain identity")
            if not isinstance(role, str) or role not in ALLOWED_CHAIN_ROLES:
                errors.append(f"{context}.role must be one of {sorted(ALLOWED_CHAIN_ROLES)}")
            if _is_identity(source_chain, CHAIN_RE) and _is_identity(campaign_chain, CHAIN_RE):
                declared_chain_pairs.add((source_chain, campaign_chain))
            if isinstance(source_chain, str):
                if source_chain in source_chain_ids:
                    errors.append("source_chain_id values must be unique")
                source_chain_ids.add(source_chain)
            if isinstance(campaign_chain, str):
                if campaign_chain in chain_by_campaign:
                    errors.append("campaign_chain_id values must be unique")
                else:
                    chain_by_campaign[campaign_chain] = row
                if role == "target":
                    target_chain_ids.add(campaign_chain)
        if not target_chain_ids:
            errors.append("chains must contain at least one role=target mapping")

    site_mappings: list[tuple[str, tuple[str, str, str | None, str, int]]] = []
    site = _check_object(
        root.get("site"),
        required=SITE_FIELDS,
        optional=None,
        context="site",
        errors=errors,
    )
    if site is not None:
        if not _is_identity(site.get("site_id")):
            errors.append(f"site.site_id {IDENTITY_REQUIREMENT}")
        mode = site.get("mode")
        if not isinstance(mode, str) or mode not in ALLOWED_SITE_MODES:
            errors.append(
                f"site.mode must be one of {sorted(ALLOWED_SITE_MODES)} and provide explicit site residues"
            )
        if not _is_unambiguous_text(site.get("numbering_scheme")):
            errors.append("site.numbering_scheme must be explicit and non-placeholder text")
        if not _is_unambiguous_text(site.get("evidence")):
            errors.append("site.evidence must be explicit and non-placeholder text")

        residues = site.get("residues")
        canonical_keys: set[tuple[str, int]] = set()
        author_keys: set[tuple[str, str, str | None]] = set()
        if not isinstance(residues, list) or not residues:
            errors.append("site.residues must be a non-empty array")
        else:
            for index, value in enumerate(residues):
                context = f"site.residues[{index}]"
                residue = _check_object(
                    value,
                    required=RESIDUE_REQUIRED,
                    optional=RESIDUE_OPTIONAL,
                    context=context,
                    errors=errors,
                )
                if residue is None:
                    continue
                campaign_chain = residue.get("campaign_chain_id")
                campaign_number = residue.get("campaign_residue_number")
                author_number = residue.get("author_residue_number")
                insertion_code = residue.get("insertion_code")
                if not _is_identity(campaign_chain, CHAIN_RE):
                    errors.append(f"{context}.campaign_chain_id must be an explicit chain identity")
                elif campaign_chain not in chain_by_campaign:
                    errors.append(f"{context}.campaign_chain_id is absent from chains")
                elif campaign_chain not in target_chain_ids:
                    errors.append(f"{context}.campaign_chain_id must map to role=target")
                if not _is_nonnegative_integer(campaign_number, positive=True):
                    errors.append(f"{context}.campaign_residue_number must be a positive whole number")
                if not isinstance(author_number, str) or AUTHOR_NUMBER_RE.fullmatch(author_number) is None:
                    errors.append(
                        f"{context}.author_residue_number must be an integer string without an insertion code"
                    )
                if insertion_code is not None and (
                    not isinstance(insertion_code, str)
                    or INSERTION_CODE_RE.fullmatch(insertion_code) is None
                ):
                    errors.append(
                        f"{context}.insertion_code must be null or one uppercase alphanumeric character"
                    )
                if "evidence" in residue and not _is_unambiguous_text(residue.get("evidence")):
                    errors.append(f"{context}.evidence must be explicit and non-placeholder text")

                if isinstance(campaign_chain, str) and _is_nonnegative_integer(
                    campaign_number, positive=True
                ):
                    canonical = campaign_chain, campaign_number
                    if canonical in canonical_keys:
                        errors.append("site.residues contains a duplicate campaign residue")
                    canonical_keys.add(canonical)
                mapping = chain_by_campaign.get(campaign_chain) if isinstance(campaign_chain, str) else None
                source_chain = mapping.get("source_chain_id") if isinstance(mapping, dict) else None
                if (
                    isinstance(source_chain, str)
                    and isinstance(author_number, str)
                    and AUTHOR_NUMBER_RE.fullmatch(author_number) is not None
                    and (
                        insertion_code is None
                        or (
                            isinstance(insertion_code, str)
                            and INSERTION_CODE_RE.fullmatch(insertion_code) is not None
                        )
                    )
                ):
                    author = source_chain, author_number, insertion_code
                    if author in author_keys:
                        errors.append("site.residues contains a duplicate author residue")
                    author_keys.add(author)
                    if _is_nonnegative_integer(campaign_number, positive=True):
                        site_mappings.append(
                            (
                                context,
                                (
                                    source_chain,
                                    author_number,
                                    insertion_code,
                                    campaign_chain,
                                    campaign_number,
                                ),
                            )
                        )

    if residue_map is not None and residue_map[3] is not None:
        _validate_residue_map_csv(
            residue_map[3],
            declared_chain_pairs=declared_chain_pairs,
            site_mappings=site_mappings,
            errors=errors,
        )

    errors.extend(_portable_text_findings(root))
    return errors


def _read_lock(path: Path) -> Any:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ValueError(f"cannot inspect lock file: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise ValueError("lock file must not be a symlink")
    if not stat.S_ISREG(mode):
        raise ValueError("lock path must be a regular file")
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if opened.st_size > MAX_LOCK_BYTES:
            raise ValueError(f"lock file exceeds the {MAX_LOCK_BYTES}-byte limit")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw = handle.read(MAX_LOCK_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"cannot read lock file: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > MAX_LOCK_BYTES:
        raise ValueError(f"lock file exceeds the {MAX_LOCK_BYTES}-byte limit")
    try:
        return strict_json.loads(raw)
    except strict_json.StrictJSONError as exc:
        raise ValueError(f"invalid UTF-8 JSON: {exc}") from exc


def _artifact_root(lock_path: Path, explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root
    if lock_path.parent.name == "locks":
        return lock_path.parent.parent
    return lock_path.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        help="Directory that artifact-reference paths resolve from. Defaults to the bundle root for locks/<file>.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        payload = _read_lock(args.lock)
        errors = validate(payload, _artifact_root(args.lock, args.artifact_root))
    except Exception as exc:  # Keep all untrusted-input failures structured.
        errors = [f"target/site lock validation failed: {type(exc).__name__}: {exc}"]

    result = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("PASS" if not errors else "FAIL")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
