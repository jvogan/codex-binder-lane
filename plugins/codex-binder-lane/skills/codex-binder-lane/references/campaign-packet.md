# Campaign packet contract

Use this contract to assemble and verify a Binder Lane campaign before an executor receives it. `campaign_packet.py` is a local materializer and verifier; it never starts a provider job.

## Required inputs

Materialization accepts four positional paths:

1. a validated `codex-binder-plan.json`;
2. a validated target/site lock;
3. a validated capability qualification ledger;
4. a new output directory.

The command rejects an existing output path. It also rejects source-contract mismatches across campaign IDs, target identity, source locks, chain mappings, site residues, ordered stages, capabilities, bound routes, providers, and prices.

Target artifact paths resolve under `--artifact-root`. If you omit that option, a target lock under `locks/` resolves from the directory that contains `locks/`; another target lock resolves from its own directory. The materializer rejects absolute paths, traversal, symlinks, changed hashes, changed byte counts, and non-regular files.

## Materialize a packet

```bash
ARTIFACT_ROOT=artifact-root
python3 <skill-directory>/scripts/campaign_packet.py materialize \
  codex-binder-plan.json \
  target-site-lock.json \
  qualification-ledger.json \
  campaign-packet \
  --artifact-root "$ARTIFACT_ROOT"
```

The materializer copies the exact plan, lock, qualification ledger, primary target input, and residue map. It writes these derived files:

- `campaign/stage-graph.json` preserves the declared stage order without inferring additional dependencies;
- `campaign/status.json` records blockers, cost fields, claim fields, and dispatch state;
- `campaign/report.md` projects the same control-plane state for a reader;
- `campaign/materialization-receipt.json` records local inputs and outputs;
- `campaign/packet-manifest.json` hashes every packet payload;
- `campaign/packet-manifest.sha256` hashes the manifest bytes.

The packet ID is the SHA-256 of a canonical record of the exact source-contract and target-artifact references. Equal inputs produce equal packet files.

## Interpret command results

`materialize` returns status 0 after it writes a valid packet. The packet may still contain dispatch blockers, so status 0 means `packet materialized`, not `campaign authorized` or `job started`.

```bash
python3 <skill-directory>/scripts/campaign_packet.py status campaign-packet
```

`status` returns status 0 only after it verifies the manifest sidecar, exact file set, payload hashes and byte counts, source contracts, packet ID, and deterministic derived files. Any edited, added, removed, replaced, or symlinked file invalidates the packet.

```bash
python3 <skill-directory>/scripts/campaign_packet.py resume-check campaign-packet
```

`resume-check` performs the same read-only verification, returns status 2, and never dispatches work. Treat status 2 as `verified but blocked`, not as an execution failure. Use `--json` with any subcommand for a machine-readable result.

## Dispatch and claim boundary

Qualification schema v1 records identity, license, route, egress, price, artifact-type, and ordered evidence-state fields. It has no hashed references to the records that support those fields. The materializer therefore adds this blocker to every v1 packet:

`qualification schema v1 does not bind supporting evidence references; dispatch remains disabled`

The materializer claim ceiling is always `plan-only`, even when a source contract declares a higher ceiling. The packet records the lowest declared source ceiling separately. Packet creation and verification use no network or provider call and incur no campaign-provider spend.

Do not edit an immutable packet. Correct a source contract and materialize a new packet. A separate [companion receipt overlay contract](companion-receipt-overlay.md) can import and verify one completed or failed external stage receipt plus its declared outputs. It keeps the base packet `plan-only`, is capped at `transport-proven`, and is not an executor, provider verifier, or scientific-validation mechanism.
