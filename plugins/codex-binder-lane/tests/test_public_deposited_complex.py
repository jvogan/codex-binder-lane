from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "codex-binder-lane" / "scripts" / "evaluate_deposited_complex.py"
SPEC = importlib.util.spec_from_file_location("evaluate_deposited_complex", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def atom(
    *,
    label: str,
    auth: str,
    entity: str,
    residue: str,
    component: str,
    atom_id: str,
    element: str,
    x: float,
) -> object:
    return MODULE.Atom(label, auth, entity, residue, None, component, atom_id, element, x, 0.0, 0.0)


class PublicDepositedComplexTests(unittest.TestCase):
    def test_synthetic_atom_rows_compute_heavy_contacts_and_exclude_water(self) -> None:
        geometry = MODULE.evaluate_atoms(
            [
                atom(label="A", auth="L", entity="1", residue="10", component="GLY", atom_id="CA", element="C", x=0.0),
                atom(label="A", auth="L", entity="1", residue="11", component="HOH", atom_id="O", element="O", x=0.1),
                atom(label="A", auth="L", entity="1", residue="12", component="GLY", atom_id="H", element="H", x=0.2),
                atom(label="B", auth="A", entity="2", residue="20", component="TYR", atom_id="CZ", element="C", x=3.5),
                atom(label="B", auth="A", entity="2", residue="21", component="TYR", atom_id="CZ", element="C", x=6.0),
            ]
        )
        self.assertEqual(geometry["heavy_atom_contact_count"], 1)
        self.assertEqual(geometry["minimum_heavy_atom_distance_angstrom"], 3.5)
        self.assertEqual(geometry["target_contacting_residues"][0]["auth_seq_id"], "10")
        self.assertEqual(geometry["binder_contacting_residues"][0]["auth_seq_id"], "20")

    def test_atom_site_parser_accepts_only_complete_required_loop(self) -> None:
        cif = """data_SYNTHETIC
loop_
_atom_site.label_asym_id
_atom_site.auth_asym_id
_atom_site.label_entity_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.label_comp_id
_atom_site.label_atom_id
_atom_site.type_symbol
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
A L 1 10 ? GLY CA C 0.0 0.0 0.0
B A 2 20 ? TYR CZ C 3.0 0.0 0.0
#
""".encode("utf-8")
        atoms = MODULE.parse_atom_site(cif)
        self.assertEqual(len(atoms), 2)
        self.assertEqual(MODULE.evaluate_atoms(atoms)["heavy_atom_contact_count"], 1)

    def test_production_cli_fails_closed_without_exact_locked_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cif = root / "synthetic.cif"
            assembly = root / "assembly.json"
            interface = root / "interface.json"
            output = root / "output"
            cif.write_text("data_SYNTHETIC\n", encoding="utf-8")
            assembly.write_text("{}\n", encoding="utf-8")
            interface.write_text("{}\n", encoding="utf-8")
            output.mkdir()
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(cif), str(assembly), str(interface), str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sealed 1ZVH", result.stderr)
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
