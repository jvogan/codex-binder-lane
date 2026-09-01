#!/usr/bin/env python3
"""Inventory local Binder Lane capabilities with an optional explicit external probe."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


RELEVANT_SKILLS = {
    "protein-binder-design": [
        "workflow",
        "backbone-generation",
        "sequence-design",
        "validation",
    ],
    "complexa-binder-design": ["workflow", "sequence-structure-codesign", "validation"],
    "complexa-design": ["sequence-structure-codesign"],
    "complexa-target": ["target-preparation", "site-conditioning"],
    "complexa-sweep": ["parameter-sweep", "sequence-structure-codesign"],
    "complexa-evaluate-pdbs": ["structure-evaluation", "interface-scoring"],
    "rfdiffusion-nim": ["backbone-generation"],
    "proteinmpnn-nim": ["sequence-design"],
    "boltz2-nim": ["complex-prediction", "validation"],
    "openfold3-nim": ["complex-prediction", "validation"],
    "openfold2-nim": ["complex-prediction", "validation"],
    "msa-search-nim": ["msa"],
    "msa-structure-prediction-pipeline": ["msa", "structure-prediction"],
    "nvmolkit-usage": ["molecular-data-processing"],
    "biohub-esm": ["sequence-modeling", "sequence-structure-codesign"],
    "structure-viewer": ["structure-inspection", "visualization"],
    "biological-sequence-viewer": ["sequence-inspection", "diversity-review"],
    "uniprot-skill": ["target-identity", "site-evidence"],
    "rcsb-pdb-skill": ["deposited-structure", "site-evidence"],
    "alphafold-skill": ["predicted-structure"],
    "quickgo-skill": ["functional-annotation"],
    "opentargets-skill": ["target-evidence"],
    "bindingdb-skill": ["binding-context"],
}

ENVIRONMENT_KEYS = [
    "NVIDIA_API_KEY",
    "NGC_API_KEY",
    "BOLTZ2_URL",
    "OPENFOLD3_URL",
    "COMPLEXA_REPO",
    "COMPLEXA_OUTPUTS",
    "FAL_KEY",
    "RFD3_FAL_URL",
    "ESMFOLD2_FAL_URL",
    "ESMFOLD2_FAST_FAL_URL",
    "PROTEINMPNN_ROOT",
    "BINDER_LANE_DOCKQ_PYTHON",
    "BIOSYMPHONY_STRUCTURE_FACTORY_ROOT",
    "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET",
    "RUNPOD_API_KEY",
    "LAMBDA_API_KEY",
    "HF_TOKEN",
]

EXECUTABLES = [
    "python3",
    "codex",
    "git",
    "docker",
    "modal",
    "runpodctl",
    "hf",
]

BIOSYMPHONY_DRIVER = Path("scripts/structure_factory/binder_lane_round.py")
BIOSYMPHONY_PROBE_TIMEOUT_SECONDS = 60


class InventoryError(ValueError):
    """Raised when a requested inventory operation is unsafe or invalid."""


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def plugin_manifests() -> list[dict[str, Any]]:
    home = Path.home()
    roots = [
        home / ".codex" / "plugins" / "cache",
        home / ".cache" / "codex-runtimes",
        home / "plugins",
    ]
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("plugin.json"):
            if path.parent.name != ".codex-plugin":
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            manifest = read_json(path)
            if not manifest:
                continue
            found.append(
                {
                    "name": manifest.get("name"),
                    "version": manifest.get("version"),
                    "description": manifest.get("description"),
                    "path": str(path),
                    "evidence_state": "filesystem-visible",
                }
            )
    return sorted(
        found, key=lambda row: (str(row.get("name")), str(row.get("version")))
    )


def frontmatter_name(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            text = handle.read(8192)
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    match = re.search(r"(?m)^name:\s*[\"']?([^\n\"']+)", text)
    return match.group(1).strip() if match else None


def relevant_skills() -> list[dict[str, Any]]:
    home = Path.home()
    roots = [
        home / ".codex" / "plugins" / "cache",
        home / ".codex" / "skills",
        home / ".agents" / "skills",
        home / "plugins",
    ]
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("SKILL.md"):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            name = frontmatter_name(path)
            if not name:
                continue
            short_name = name.split(":")[-1]
            roles = RELEVANT_SKILLS.get(name) or RELEVANT_SKILLS.get(short_name)
            if roles:
                found.append(
                    {
                        "name": name,
                        "roles": roles,
                        "path": str(path),
                        "evidence_state": "filesystem-visible",
                    }
                )
    return sorted(found, key=lambda row: (str(row["name"]), str(row["path"])))


def codex_plugin_listing() -> dict[str, Any]:
    codex = shutil.which("codex")
    if not codex:
        return {"ok": False, "error": "codex executable not found", "marketplaces": []}
    try:
        run = subprocess.run(
            [codex, "plugin", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "marketplaces": []}
    marketplaces: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in run.stdout.splitlines():
        if line.startswith("Marketplace `"):
            name = line.split("`", 2)[1]
            current = {"name": name, "plugins": []}
            marketplaces.append(current)
            continue
        if (
            not current
            or not line.strip()
            or line.lstrip().startswith("PLUGIN")
            or line.startswith("/")
        ):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 3 and "@" in parts[0]:
            row: dict[str, Any] = {"id": parts[0], "status": parts[1]}
            if len(parts) == 3:
                row["path"] = parts[2]
            else:
                row["version"] = parts[2]
                row["path"] = parts[3]
            current["plugins"].append(row)
    return {
        "ok": run.returncode == 0,
        "returncode": run.returncode,
        "error": run.stderr.strip() or None,
        "marketplaces": marketplaces,
    }


def candidate_biosymphony_roots(workspace: Path) -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("BIOSYMPHONY_STRUCTURE_FACTORY_ROOT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([workspace, *workspace.parents])
    home = Path.home()
    for github_root in home.glob("github*"):
        candidates.append(github_root / "bio-symphony-structure-factory")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
        if absolute not in seen:
            seen.add(absolute)
            unique.append(absolute)
    return unique


def _biosymphony_paths(root: Path) -> tuple[Path, Path]:
    selected_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    return selected_root, selected_root / BIOSYMPHONY_DRIVER


def _driver_symlink(root: Path) -> Path | None:
    current = root
    for part in BIOSYMPHONY_DRIVER.parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def biosymphony_candidates(workspace: Path) -> list[dict[str, Any]]:
    """Return filesystem candidates without invoking code from those checkouts."""

    results: list[dict[str, Any]] = []
    for root in candidate_biosymphony_roots(workspace):
        selected_root, driver = _biosymphony_paths(root)
        if not driver.is_file() and not driver.is_symlink():
            continue
        symlinked_driver_component = _driver_symlink(selected_root)
        results.append(
            {
                "root": str(selected_root),
                "driver": str(driver),
                "agents_md": (
                    str(selected_root / "AGENTS.md")
                    if (selected_root / "AGENTS.md").is_file()
                    else None
                ),
                "external_code_executed": False,
                "probe_allowed": (
                    selected_root.is_dir()
                    and not selected_root.is_symlink()
                    and symlinked_driver_component is None
                    and driver.is_file()
                ),
                "symlinked_path": (
                    str(selected_root)
                    if selected_root.is_symlink()
                    else str(symlinked_driver_component)
                    if symlinked_driver_component is not None
                    else None
                ),
            }
        )
    return results


def _validated_biosymphony_probe_paths(root: Path) -> tuple[Path, Path]:
    selected_root, driver = _biosymphony_paths(root)
    if selected_root.is_symlink():
        raise InventoryError("selected BioSymphony root must not be a symlink")
    if not selected_root.exists():
        raise InventoryError("selected BioSymphony root does not exist")
    if not selected_root.is_dir():
        raise InventoryError("selected BioSymphony root must be a directory")

    symlinked_driver_component = _driver_symlink(selected_root)
    if symlinked_driver_component is not None:
        raise InventoryError(
            "selected BioSymphony driver path must not contain a symlink: "
            f"{symlinked_driver_component}"
        )
    if not driver.is_file():
        raise InventoryError(
            "selected BioSymphony root does not contain the exact driver path "
            f"{BIOSYMPHONY_DRIVER.as_posix()}"
        )
    return selected_root, driver


def probe_biosymphony_root(root: Path) -> dict[str, Any]:
    """Run the menu command for one exact, explicitly selected checkout root."""

    selected_root, driver = _validated_biosymphony_probe_paths(root)
    record: dict[str, Any] = {
        "root": str(selected_root),
        "driver": str(driver),
        "agents_md": (
            str(selected_root / "AGENTS.md")
            if (selected_root / "AGENTS.md").is_file()
            else None
        ),
        "external_code_executed": True,
        "menu": {"ok": False},
    }
    try:
        run = subprocess.run(
            [sys.executable, str(driver), "menu", "--json"],
            cwd=selected_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=BIOSYMPHONY_PROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(run.stdout) if run.stdout.strip() else {}
        tools = payload.get("tools", []) if isinstance(payload, dict) else []
        record["menu"] = {
            "ok": run.returncode == 0
            and isinstance(payload, dict)
            and bool(payload.get("ok")),
            "profile_id": payload.get("profile_id")
            if isinstance(payload, dict)
            else None,
            "tool_count": payload.get("tool_count")
            if isinstance(payload, dict)
            else None,
            "selectable_count": payload.get("selectable_count")
            if isinstance(payload, dict)
            else None,
            "selectable_tool_ids": [
                item.get("tool_id")
                for item in tools
                if isinstance(item, dict) and item.get("selectable") is True
            ],
            "error": run.stderr.strip() or None,
        }
    except subprocess.TimeoutExpired:
        record["menu"] = {
            "ok": False,
            "error": f"probe timed out after {BIOSYMPHONY_PROBE_TIMEOUT_SECONDS} seconds",
        }
    except (OSError, json.JSONDecodeError) as exc:
        record["menu"] = {"ok": False, "error": str(exc)}
    return record


def build_inventory(
    workspace: Path,
    probe_root: Path | None = None,
    *,
    probe_codex_cli: bool = False,
) -> dict[str, Any]:
    probe = probe_biosymphony_root(probe_root) if probe_root is not None else None
    plugin_listing = (
        codex_plugin_listing()
        if probe_codex_cli
        else {
            "ok": False,
            "status": "not-probed",
            "error": None,
            "marketplaces": [],
        }
    )
    external_code_executed = probe is not None or probe_codex_cli
    warning = (
        "Filesystem visibility and CLI listing do not prove current-task visibility, "
        "authentication, runtime readiness, adapter binding, scientific qualification, or authorization."
    )
    if external_code_executed:
        warning += (
            " An explicit probe executed external code; its network and provider behavior "
            "is not verified by this inventory."
        )
    return {
        "schema_version": "codex-binder-capability-inventory/v1",
        "workspace": str(workspace),
        "network_or_provider_calls": False if not external_code_executed else None,
        "external_code_executed": external_code_executed,
        "warning": warning,
        "executables": {name: shutil.which(name) for name in EXECUTABLES},
        "environment_presence": {
            name: bool(os.environ.get(name)) for name in ENVIRONMENT_KEYS
        },
        "plugin_manifests": plugin_manifests(),
        "codex_plugin_listing": plugin_listing,
        "relevant_skills": relevant_skills(),
        "biosymphony": biosymphony_candidates(workspace),
        "biosymphony_probe": probe,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--probe-codex-cli",
        action="store_true",
        help=(
            "Execute the codex executable resolved from PATH to list installed plugins. "
            "The current task's callable skill catalog remains authoritative."
        ),
    )
    parser.add_argument(
        "--probe-biosymphony-root",
        type=Path,
        help=(
            "Execute the menu command from exactly this selected BioSymphony checkout root. "
            "The root and driver must exist and must not be symlinks."
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit pretty JSON")
    args = parser.parse_args()

    workspace = args.workspace.expanduser().resolve()
    try:
        payload = build_inventory(
            workspace,
            args.probe_biosymphony_root,
            probe_codex_cli=args.probe_codex_cli,
        )
    except InventoryError as exc:
        print(f"capability_inventory: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2 if args.json else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
