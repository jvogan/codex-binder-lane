# Evidence bundle contracts

Use these versioned contracts for every emitted Binder Lane bundle. The plan authorizes work; the bundle records what actually happened. A downstream file may preserve or lower the plan's claim ceiling, never raise it.

## Required identities

Every machine-readable artifact carries a `schema_version` and `campaign_id`. Candidate-bearing artifacts also carry stable `candidate_id` values. IDs are immutable within a campaign.

The current v1 records are:

- `codex-binder-target-site-lock/v1` for immutable source, chain, numbering, residue-map, site, confidentiality, and claim locks;
- `codex-binder-bundle-manifest/v1` for the sorted payload ledger;
- `codex-binder-stage-receipt/v1` for one attempted or completed stage;
- `codex-binder-lineage/v1` for candidate ancestry and artifact ownership;
- `codex-binder-metrics/v1` for metric definitions, values, null states, counts, and ranking status;
- structure, sequence, renderer, and video handoff v1 records for review or media surfaces;
- `codex-binder-media-scenes/v1` and the storyboard v1 record for renderer-neutral visual intent;
- `codex-binder-closeout/v1` for the machine-readable report projection.
- `codex-binder-delivery-index/v2` for the curated target/site context, report, sequence, metrics, target–binder structures, site-highlighted renders, video, viewer, and browser-evidence inventory.

## Artifact references

An artifact reference contains a safe relative POSIX `path`, lowercase SHA-256 digest, and exact byte count. Absolute paths, parent traversal, backslashes, symlinks, non-regular files, and unmanifested payloads fail validation.

The manifest lists every payload exactly once in lexical order. It does not list itself or its hash sidecar. The sidecar hashes the exact canonical manifest bytes.

An exhaustive archive manifest and a curated delivery index serve different purposes. The archive may retain execution workspaces and logs. The delivery index contains only artifacts intended for inspection or later computational use. Hash coverage of vendored examples, dependency trees, caches, or tool source does not satisfy delivery closeout.

## Target and site lock

Execute bundles require a target/site lock referenced by the plan, summary, and all candidate review or media packets. It preserves source and normalized-input hashes, source and campaign chain identifiers, explicit numbering, insertion codes, residue-map evidence, confidentiality, and the allowed claim ceiling.

Author numbering is provenance, not the canonical join key. Use campaign chain plus campaign residue number across metrics, handoffs, scenes, and reports.

## Counts, metrics, and nulls

Counts are non-negative whole numbers with explicit semantics. Transport counts do not imply scientific funnel success.

Each metric has an evidence class, direction, and unit. A measured value is finite and numeric. `not-measured` and `failed` states use `null`, never zero. A transport-only canary keeps every scientific metric null and remains unranked.

## Surface execution state

Handoffs report four independent states:

- packet emission;
- runtime detection;
- invocation;
- output validation.

An emitted packet proves only that the handoff was materialized and hashed. An unprobed or unavailable runtime cannot have a completed invocation. A completed invocation does not imply that its output passed validation. Output artifacts must be manifest-backed, and a not-run invocation must have none.

Runtime verification belongs in an overlay receipt tied to the sealed bundle-manifest hash. Do not rewrite a deterministic source bundle merely to record that a viewer or renderer was exercised later.

## Receipts and closeout

Receipts separate `route_kind` from provider identity, preserve inputs and outputs by artifact reference, record counts, cost state, cleanup, failure, and claim ceiling, and name candidate lineage explicitly.

The terminal closeout receipt references the plan, target lock, report, summary, substantive artifacts, and all earlier receipts. The summary may name receipt IDs, but it does not hash the terminal receipt; this avoids a cyclic self-attestation.

The Markdown report and JSON summary must agree on identity, counts, costs, ranking, scientific nulls, handoff states, output counts, limitations, and claim ceiling. Validation belongs to the validator or its receipt, never to the report's own prose.

When HTML, visible sequences, structure visuals, or video are promised, the terminal presentation closeout also references a passing `validate_delivery.py` result. Static HTML markers bind each requested visible sequence, download, decoder-checked structure render, raw coordinate file, and rendered video to the curated delivery index. Browser evidence checks the built output rather than only its source files.
