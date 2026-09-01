# Deterministic synthetic transport canary

Use this fixture only to test Binder Lane's portable evidence-bundle contract. It emits no meaningful biological sequence, makes no provider call, performs no scientific prediction, and never exceeds the `transport-proven` claim ceiling.

Build into a new or empty user-supplied directory:

```bash
python3 scripts/build_fixture_bundle.py ./canary-bundle
python3 scripts/validate_bundle.py ./canary-bundle
```

The bundle contains:

- X-only sentinel FASTA and A3M records;
- an immutable synthetic target/site lock linked from the plan and handoffs;
- one-atom placeholder PDB and mmCIF coordinate files plus a residue map;
- candidate metrics whose scientific score and confidence are `null`;
- candidate lineage and deterministic stage receipts;
- a readable report and machine-readable summary;
- Structure Viewer and Sequence Viewer portable handoffs;
- renderer-neutral scenes and storyboard metadata;
- hook-only PyMOL, ChimeraX, Remotion, and HyperFrames JSON handoffs;
- a sorted artifact manifest and a SHA-256 sidecar for that manifest.

Ranking: `Unranked`. Scientific score and confidence: `Not measured`. Observed cost: `$0.00`. Optional surfaces: packet emitted; runtime unprobed; invocation not run; output validation not run; outputs `0`.

The validator rejects missing or extra files, symlinks, unsafe paths, hash or size mismatches, noncanonical JSON, count drift, incorrect candidate references, non-null scientific values, ranking or claim escalation, broken receipt dependencies, impossible surface states, report/summary drift, unsafe media hooks, and changes to the fixed sentinel formats.

The canary is deliberately renderer-independent. Viewer or video availability is not required for the portable bundle to validate, and a hook-only handoff never claims that a render occurred.
