# Codex Binder Lane 0.2.0

Codex Binder Lane 0.2.0 adds validated target/site locks, capability qualification ledgers, deterministic local packets, and locked local evaluation paths. The release starts no provider job and keeps every schema-v1 packet at a `plan-only` materializer claim ceiling.

The plugin manifest version is `0.2.0+codex.20260831003417`. The public source tag is `v0.2.0`.

## Included

- `validate_plan.py` checks campaign decisions, authorization, cost, fanout, controls, handoffs, and claim ceilings.
- `validate_target_site.py` checks source identity, artifact hashes and byte counts, chain mappings, residue maps, site residues, portability, and local path safety.
- `validate_qualification.py` checks capability identity, revision, license, route, provider, egress, price, artifact type, ordered evidence state, and claim integrity.
- `campaign_packet.py` materializes a hash-verified packet and checks its exact file set, source contracts, packet ID, and deterministic derived files.
- The synthetic canary checks software transport without biological data.
- The locked 1ZVH workflow evaluates deposited coordinates locally and forbids generation, prediction, ranking, upload, and provider calls.

## Command boundary

`campaign_packet.py materialize` can return status 0 when packet creation succeeds but dispatch remains blocked. `campaign_packet.py status` verifies the packet and returns status 0 for a valid blocked packet. `campaign_packet.py resume-check` performs the same read-only verification, returns status 2, and starts no work.

Qualification schema v1 records evidence states without hashed references to supporting records. Every v1 packet therefore includes a dispatch blocker. A source contract can record a higher declared ceiling, but the materializer ceiling remains `plan-only`.

## Verification

The release gate checks the exact public file set and its receipt, runs the repository and plugin suites, and compiles the Python sources on Python 3.10 through 3.14. Release verification makes no provider call.

Run the same checks:

```bash
python3 scripts/verify_public_export.py
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s plugins/codex-binder-lane/tests -v
python3 -m compileall -q scripts tests plugins/codex-binder-lane
```

The detached release checksums identify the final receipt and source archive. They stay outside the receipt-covered tree so the receipt does not contain its own hash.
