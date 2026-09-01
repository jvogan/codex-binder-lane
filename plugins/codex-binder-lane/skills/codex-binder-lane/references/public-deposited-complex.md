# Locked public deposited-complex evaluation

`scripts/evaluate_deposited_complex.py` is an offline, evaluation-only receipt
for a single already-deposited public complex. It does not download a structure
or metadata, generate a sequence or structure, run a prediction, rank a
candidate, upload data, or use paid compute.

The production command accepts exactly four local paths:

```bash
python3 scripts/evaluate_deposited_complex.py \
  1zvh.cif assembly.json interface.json ./empty-output
```

The output directory must be new or empty. It receives deterministic
`evaluation.json`, `report.md`, and `artifact-manifest.json` files. The
manifest hashes the two result files; it intentionally does not hash itself.

## Sealed input contract

The command fails closed unless all local inputs match these locks exactly:

| Input | Lock |
| --- | --- |
| CIF | 1ZVH, entry version 1.6; 233357 bytes; SHA-256 `6782554510e77d276d5a93e3892bc78136c6bee39b22782f88c874cbf2701226` |
| Assembly metadata | assembly 1; canonical JSON; 2910 bytes; SHA-256 `d77e88b1aad153a91eee5ff844362e085471629b8254691760bffa996dad2a01` |
| Interface metadata | interface `1ZVH-1.1`; canonical JSON; 9740 bytes; SHA-256 `8b10185eeec7d55f9a9fff1c2f733abf0039264d72e0791d04973697844edcc0` |

Canonical JSON means `json.dumps(value, sort_keys=True,
separators=(",", ":"), ensure_ascii=True) + "\\n"`. The evaluator does not
fetch replacement files when a lock fails.

## Geometry calculation and boundary

The evaluator reads only the local mmCIF `_atom_site` loop and requires the
locked chain identities:

- target: label asym `A`, author asym `L`, entity `1`;
- deposited partner: label asym `B`, author asym `A`, entity `2`.

It excludes water (`HOH`, `WAT`, and `DOD`) and hydrogen atoms, then reports
all heavy-atom pairs at or below 4.0 Å, their minimum distance, and the
contacting author-numbered residues. A missing locked chain fails the run.

The report remains `unranked` with a `transport-proven` claim ceiling. Contact
geometry is a coordinate observation, not a binding, affinity, specificity,
prediction or generated-candidate result. The receipt explicitly records
generation, prediction, upload, and network access as not run/not used and
observed cost as $0.00.

For tests, use the module's atom-row helper with synthetic coordinates. Do not
add the deposited CIF, derived coordinate assets, sequences, or generated
candidate content to the plugin or public export.
