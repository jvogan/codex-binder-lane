#!/usr/bin/env python3
"""Offline, evaluation-only geometry receipt for the locked public 1ZVH complex."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ENTRY_ID = "1ZVH"
ENTRY_VERSION = "1.6"
ASSEMBLY_ID = "1"
INTERFACE_ID = "1ZVH-1.1"
CIF_SIZE_BYTES = 233357
CIF_SHA256 = "6782554510e77d276d5a93e3892bc78136c6bee39b22782f88c874cbf2701226"
ASSEMBLY_SIZE_BYTES = 2910
ASSEMBLY_SHA256 = "d77e88b1aad153a91eee5ff844362e085471629b8254691760bffa996dad2a01"
INTERFACE_SIZE_BYTES = 9740
INTERFACE_SHA256 = "8b10185eeec7d55f9a9fff1c2f733abf0039264d72e0791d04973697844edcc0"
DISTANCE_CUTOFF_ANGSTROM = 4.0
TARGET = ("A", "L", "1")
BINDER = ("B", "A", "2")
WATER_COMPONENTS = {"HOH", "WAT", "DOD"}


class EvaluationError(ValueError):
    """A sealed evaluation input or output requirement was not met."""


@dataclass(frozen=True)
class Atom:
    label_asym_id: str
    auth_asym_id: str
    entity_id: str
    auth_seq_id: str
    insertion_code: str | None
    comp_id: str
    atom_id: str
    element: str
    x: float
    y: float
    z: float

    @property
    def chain_key(self) -> tuple[str, str, str]:
        return (self.label_asym_id, self.auth_asym_id, self.entity_id)


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_regular_bytes(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise EvaluationError(f"cannot inspect {path}: {exc}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise EvaluationError(f"input must be a regular non-symlink file: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EvaluationError(f"cannot read {path}: {exc}") from exc


def load_canonical_json(path: Path, expected_size: int, expected_sha256: str, label: str) -> dict[str, Any]:
    raw = read_regular_bytes(path)
    if len(raw) != expected_size or sha256_bytes(raw) != expected_sha256:
        raise EvaluationError(f"{label} does not match the sealed 1ZVH lock")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise EvaluationError(f"{label} must use sealed canonical JSON bytes")
    return value


def require_production_locks(cif_path: Path, assembly_path: Path, interface_path: Path) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    cif_bytes = read_regular_bytes(cif_path)
    if len(cif_bytes) != CIF_SIZE_BYTES or sha256_bytes(cif_bytes) != CIF_SHA256:
        raise EvaluationError("CIF does not match the sealed 1ZVH v1.6 bytes")
    assembly = load_canonical_json(assembly_path, ASSEMBLY_SIZE_BYTES, ASSEMBLY_SHA256, "assembly JSON")
    interface = load_canonical_json(interface_path, INTERFACE_SIZE_BYTES, INTERFACE_SHA256, "interface JSON")
    required_strings = {ENTRY_ID, ENTRY_VERSION, ASSEMBLY_ID, INTERFACE_ID}
    lock_text = json.dumps({"assembly": assembly, "interface": interface}, sort_keys=True)
    if not all(item in lock_text for item in required_strings):
        raise EvaluationError("sealed metadata does not identify the required 1ZVH assembly/interface")
    return cif_bytes, assembly, interface


def _normalise(value: str | None) -> str | None:
    if value in {None, ".", "?", ""}:
        return None
    return value


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True, posix=True)
    except ValueError as exc:
        raise EvaluationError(f"unsafe or malformed CIF token: {exc}") from exc


def parse_atom_site(cif_bytes: bytes) -> list[Atom]:
    try:
        lines = cif_bytes.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise EvaluationError("CIF must be UTF-8 text") from exc
    headers: list[str] | None = None
    values: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip().lower() != "loop_":
            index += 1
            continue
        index += 1
        loop_headers: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("_"):
            fields = _tokens(lines[index])
            if len(fields) != 1:
                raise EvaluationError("CIF loop header must be one token")
            loop_headers.append(fields[0])
            index += 1
        if not any(header.startswith("_atom_site.") for header in loop_headers):
            continue
        if not loop_headers or not all(header.startswith("_atom_site.") for header in loop_headers):
            raise EvaluationError("atom_site loop has unexpected headers")
        headers = loop_headers
        while index < len(lines):
            stripped = lines[index].strip()
            if stripped == "#":
                index += 1
                break
            if stripped.lower() == "loop_" or stripped.startswith("_") or stripped.lower().startswith("data_"):
                break
            if lines[index].startswith(";"):
                raise EvaluationError("multiline CIF values are not accepted in atom_site")
            values.extend(_tokens(lines[index]))
            index += 1
        break
    if headers is None or not values or len(values) % len(headers):
        raise EvaluationError("CIF has no complete atom_site loop")
    rows = [dict(zip(headers, values[offset : offset + len(headers)])) for offset in range(0, len(values), len(headers))]
    required = {
        "_atom_site.label_asym_id",
        "_atom_site.auth_asym_id",
        "_atom_site.label_entity_id",
        "_atom_site.auth_seq_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_atom_id",
        "_atom_site.Cartn_x",
        "_atom_site.Cartn_y",
        "_atom_site.Cartn_z",
    }
    if not required.issubset(headers):
        raise EvaluationError("CIF atom_site loop lacks required chain, residue, or coordinate columns")
    atoms: list[Atom] = []
    for row in rows:
        try:
            atoms.append(
                Atom(
                    label_asym_id=row["_atom_site.label_asym_id"],
                    auth_asym_id=row["_atom_site.auth_asym_id"],
                    entity_id=row["_atom_site.label_entity_id"],
                    auth_seq_id=row["_atom_site.auth_seq_id"],
                    insertion_code=_normalise(row.get("_atom_site.pdbx_PDB_ins_code")),
                    comp_id=row["_atom_site.label_comp_id"],
                    atom_id=row["_atom_site.label_atom_id"],
                    element=row.get("_atom_site.type_symbol", ""),
                    x=float(row["_atom_site.Cartn_x"]),
                    y=float(row["_atom_site.Cartn_y"]),
                    z=float(row["_atom_site.Cartn_z"]),
                )
            )
        except (KeyError, ValueError) as exc:
            raise EvaluationError("CIF atom_site row is malformed") from exc
    return atoms


def is_heavy_non_water(atom: Atom) -> bool:
    if atom.comp_id.upper() in WATER_COMPONENTS:
        return False
    element = atom.element.strip().upper()
    if not element:
        element = re.sub(r"^[0-9]+", "", atom.atom_id).upper()[:1]
    return element != "H"


def residue_record(atom: Atom) -> dict[str, str | None]:
    return {
        "label_asym_id": atom.label_asym_id,
        "auth_asym_id": atom.auth_asym_id,
        "entity_id": atom.entity_id,
        "auth_seq_id": atom.auth_seq_id,
        "insertion_code": atom.insertion_code,
        "comp_id": atom.comp_id,
    }


def residue_key(atom: Atom) -> tuple[str, str, str, tuple[int, str], str, str]:
    try:
        sequence_key = (0, f"{int(atom.auth_seq_id):012d}")
    except ValueError:
        sequence_key = (1, atom.auth_seq_id)
    return (*atom.chain_key, sequence_key, atom.insertion_code or "", atom.comp_id)


def evaluate_atoms(atoms: Iterable[Atom], *, enforce_production_chains: bool = True) -> dict[str, Any]:
    target_atoms = [atom for atom in atoms if atom.chain_key == TARGET and is_heavy_non_water(atom)]
    binder_atoms = [atom for atom in atoms if atom.chain_key == BINDER and is_heavy_non_water(atom)]
    if enforce_production_chains and (not target_atoms or not binder_atoms):
        raise EvaluationError("locked 1ZVH target or binder heavy atoms are absent")
    contacts = 0
    minimum: float | None = None
    target_residues: dict[tuple[str, str, str, tuple[int, str], str, str], Atom] = {}
    binder_residues: dict[tuple[str, str, str, tuple[int, str], str, str], Atom] = {}
    for target in target_atoms:
        for binder in binder_atoms:
            distance = math.dist((target.x, target.y, target.z), (binder.x, binder.y, binder.z))
            if distance <= DISTANCE_CUTOFF_ANGSTROM:
                contacts += 1
                minimum = distance if minimum is None else min(minimum, distance)
                target_residues[residue_key(target)] = target
                binder_residues[residue_key(binder)] = binder
    return {
        "heavy_atom_contact_count": contacts,
        "minimum_heavy_atom_distance_angstrom": None if minimum is None else round(minimum, 6),
        "target_contacting_residues": [residue_record(atom) for _, atom in sorted(target_residues.items())],
        "binder_contacting_residues": [residue_record(atom) for _, atom in sorted(binder_residues.items())],
    }


def artifact(path: str, data: bytes) -> dict[str, Any]:
    return {"path": path, "sha256": sha256_bytes(data), "size_bytes": len(data)}


def report_text(result: dict[str, Any]) -> str:
    geometry = result["geometry"]
    return (
        "# Locked 1ZVH deposited-complex evaluation\n\n"
        "> Evaluation-only offline geometry receipt. Claim ceiling: `transport-proven`.\n\n"
        "## Locked input\n\n"
        f"- Entry/version: `{ENTRY_ID}` / `{ENTRY_VERSION}`\n"
        f"- Assembly/interface: `{ASSEMBLY_ID}` / `{INTERFACE_ID}`\n"
        "- Target chain: label `A`, author `L`, entity `1`\n"
        "- Binder chain: label `B`, author `A`, entity `2`\n\n"
        "## Geometry receipt\n\n"
        f"- Heavy-atom contacts at or below 4.0 Å: {geometry['heavy_atom_contact_count']}\n"
        f"- Minimum heavy-atom distance (Å): {geometry['minimum_heavy_atom_distance_angstrom']}\n"
        f"- Contacting target residues: {len(geometry['target_contacting_residues'])}\n"
        f"- Contacting binder residues: {len(geometry['binder_contacting_residues'])}\n\n"
        "## Evidence boundary\n\n"
        "This receipt performs no generation, prediction, ranking, upload, or network fetch. "
        "It records deposited-coordinate geometry only; it is not an affinity, specificity, or validation claim. "
        "Observed cost: $0.00.\n"
    )


def prepare_output_directory(path: Path) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise EvaluationError("output must be an empty non-symlink directory")
        if any(path.iterdir()):
            raise EvaluationError("output directory must be empty")
        return
    path.mkdir(parents=True)


def evaluate(cif_path: Path, assembly_path: Path, interface_path: Path, output: Path) -> dict[str, Any]:
    cif_bytes, _, _ = require_production_locks(cif_path, assembly_path, interface_path)
    prepare_output_directory(output)
    geometry = evaluate_atoms(parse_atom_site(cif_bytes))
    result = {
        "schema_version": "codex-binder-deposited-complex-evaluation/v1",
        "operation": "evaluation-only",
        "entry": {"id": ENTRY_ID, "version": ENTRY_VERSION, "assembly_id": ASSEMBLY_ID, "interface_id": INTERFACE_ID},
        "chain_locks": {
            "target": {"label_asym_id": "A", "auth_asym_id": "L", "entity_id": "1"},
            "binder": {"label_asym_id": "B", "auth_asym_id": "A", "entity_id": "2"},
        },
        "input_artifacts": {
            "cif": artifact(cif_path.name, cif_bytes),
            "assembly": artifact(assembly_path.name, read_regular_bytes(assembly_path)),
            "interface": artifact(interface_path.name, read_regular_bytes(interface_path)),
        },
        "geometry": geometry,
        "distance_cutoff_angstrom": DISTANCE_CUTOFF_ANGSTROM,
        "water_excluded": True,
        "ranking_status": "unranked",
        "claim_ceiling": "transport-proven",
        "actions": {"generation": "not-run", "prediction": "not-run", "upload": "not-run", "network": "not-used"},
        "observed_cost_usd": 0,
    }
    evaluation_bytes = (json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    report_bytes = report_text(result).encode("utf-8")
    manifest = {
        "schema_version": "codex-binder-deposited-complex-manifest/v1",
        "claim_ceiling": "transport-proven",
        "files": [artifact("evaluation.json", evaluation_bytes), artifact("report.md", report_bytes)],
    }
    (output / "evaluation.json").write_bytes(evaluation_bytes)
    (output / "report.md").write_bytes(report_bytes)
    (output / "artifact-manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cif", type=Path, help="sealed local 1ZVH mmCIF file")
    parser.add_argument("assembly_json", type=Path, help="sealed assembly metadata JSON")
    parser.add_argument("interface_json", type=Path, help="sealed interface metadata JSON")
    parser.add_argument("output", type=Path, help="new or empty output directory")
    args = parser.parse_args()
    try:
        result = evaluate(args.cif, args.assembly_json, args.interface_json, args.output)
    except (EvaluationError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "claim_ceiling": result["claim_ceiling"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
