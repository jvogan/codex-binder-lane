# Companion receipt overlay contract

`campaign_overlay.py` imports and verifies one immutable companion-stage receipt against an already verified Binder Lane campaign packet. It is a provider-neutral evidence boundary, not an executor: it never contacts a provider, starts or resumes a job, spends money, or changes the base packet.

The base packet remains `plan-only`, dispatch-disabled, and immutable. A completed overlay can claim at most `transport-proven`: the importer hash-binds an external receipt and the declared copied outputs. It does not independently establish that a remote provider executed work, and it does not establish scientific validity, ranking, or binding.

## Import one stage receipt

The companion writes its own receipt and output files first. The receipt must name one already frozen plan and qualification stage. Then import it into a new directory:

```bash
python3 <skill-directory>/scripts/campaign_overlay.py import-stage \
  campaign-packet \
  companion-stage-receipt.json \
  companion-overlay \
  --artifact-root companion-output-root \
  --json
```

The command verifies the base packet before reading the receipt. It rejects an existing or packet-overlapping output directory, duplicate JSON keys at any depth, symlinks, unsafe or Windows-unrepresentable paths, case-folded or Unicode-normalized path aliases and file/directory prefix collisions, changed hashes, changed byte counts, extra fields, credential-like values, and private or local endpoints. Declared output count and aggregate bytes are checked before any output file is read. Recognized UTF-8 text outputs are also scanned for credential-like content, embedded signed URLs, private endpoints, and ambiguous JSON before retention. It copies only the receipt-declared `artifacts/...` outputs into the new overlay and verifies the staged overlay before publishing the new directory.

The importer is an evidence boundary, not a general-purpose sanitizer. Older plans use conservative defaults of 30 outputs and 640 MiB per overlay. New plans declare `execution.artifact_budget` with per-overlay output-count, aggregate-byte, and per-artifact limits; the importer enforces the frozen values plus hard safety ceilings. The file-count ceiling is configurable up to 4,094 outputs, while the byte ceilings stay conservative because the current importer verifies payloads in memory. Split a larger stage result into separately imported, hash-bound sibling overlays, or keep bulk cloud data outside the overlay and import only the declared review artifacts. Binary files and outputs with unknown extensions are retained byte-for-byte after their declared hashes and sizes are verified, but their contents are not inspected. Recognized text outputs larger than 16 MiB are rejected rather than decoded and recursively scanned in memory. Treat retained artifacts as potentially sensitive and review them before publication.

It writes:

- `receipts/companion-stage-receipt.json`, the exact external receipt bytes;
- `artifacts/...`, exact copied companion outputs;
- `overlay-status.json`, a deterministic local statement that the importer did not dispatch, use a network, or independently verify provider execution;
- `overlay-manifest.json` and `overlay-manifest.sha256`, which seal the exact overlay file set.

The overlay ID binds the verified base packet ID and manifest digest, exact receipt bytes, and copied output hashes. Equal inputs produce equal overlays.

## Receipt shape

The receipt is strict JSON with exactly these fields:

```json
{
  "schema_version": "codex-binder-companion-stage-receipt/v1",
  "receipt_id": "portable-receipt-id",
  "campaign_id": "frozen-campaign-id",
  "base_packet_id": "base-packet-sha256",
  "base_manifest_sha256": "base-manifest-sha256",
  "stage_id": "frozen-stage-id",
  "capability": {"id": "qualified-capability-id", "revision": "qualified-revision"},
  "route_kind": "local-or-qualified-remote-route",
  "provider": "frozen-provider-id",
  "execution_state": "completed-or-failed",
  "provider_request_id": null,
  "inputs": [{"path": "base-artifact", "sha256": "sha256", "size_bytes": 0}],
  "outputs": [{"path": "artifacts/output", "sha256": "sha256", "size_bytes": 0}],
  "cost": {"status": "unknown", "estimate_usd": null, "observed_usd": null},
  "cleanup_state": "not-applicable",
  "claim_ceiling": "transport-proven"
}
```

All IDs must be portable identifiers. `capability`, route, and provider must exactly match both the frozen plan stage and its qualified stage. Every input must exactly equal one reference from the base packet manifest. Outputs must be lexically sorted, unique, safe relative paths under `artifacts/`, and match non-symlinked regular files beneath `--artifact-root`.

`completed` requires at least one output, `claim_ceiling: "transport-proven"`, and a terminal cleanup state of `verified` or `not-applicable`. Here, `not-applicable` means the stage created no campaign-owned cleanup resource; it does not attest to provider-internal lifecycle behavior. A completed remote route also requires a portable `provider_request_id`. `failed` requires no outputs and `claim_ceiling: "plan-only"`. The cost record distinguishes `unknown`, `estimated`, `observed`, and `not-applicable`; it does not infer a charge from a provider response.

Before materializing a packet intended to accept a later completed receipt, deliberately set the campaign plan to `mode: "execute"`, set `plan.evidence.claim_ceiling` to `transport-proven`, and set the target/site lock `claim_ceiling` to `transport-proven`. The stage and qualification ledger must describe the exact selected route and provider, and the qualification ledger must be in execute mode. The initializer intentionally starts at `plan-only`; do not raise these fields until the scientific route, authorization, and data-egress decisions are resolved. A failed-stage receipt can remain `plan-only`.

For a paid stage, `not-applicable` is not a valid cost state. Any receipt estimate must exactly match the frozen plan and qualification estimates. Unknown cost may remain explicit, and an observed cost may exceed the estimate or campaign ceiling because truthful evidence must not be discarded; the deterministic overlay status records and flags that overage.

The allowed result ceiling is the lower of the frozen plan and target/site authorization ceilings, capped by this overlay contract at `transport-proven`. The qualification-ledger v1 ceiling does not become execution evidence by itself; the imported receipt and output hashes are the new, limited transport evidence.

## Verify later

```bash
python3 <skill-directory>/scripts/campaign_overlay.py verify \
  campaign-packet \
  companion-overlay \
  --json
```

Verification rechecks the complete base packet, overlay manifest sidecar, exact overlay file set, receipt/base binding, copied output hashes, and deterministic status. Editing either packet, adding a file, replacing an output, or using a symlink makes verification fail.

The importer handles one stage at a time. For a multi-stage campaign, write one sibling overlay directory per completed or failed stage and keep the companion's native campaign record. The importer does not merge overlays, poll providers, dispatch or resume jobs, or close the campaign. A selected companion remains responsible for live execution and for provider-specific evidence beyond this portable receipt contract.

## BioSymphony hosted-Chai adapter

`normalize_biosymphony_chai_receipt.py` is the supported local adapter for one completed BioSymphony Structure Factory hosted-Chai (`fal`) prediction. It reads the native `inference-receipt.json` and exactly one matching `cofold-observations.jsonl` row, validates their mutual hashes, and emits this receipt schema plus four byte-for-byte copied artifacts: normalized complex PDB, PAE record, measurement source, and runner identity. It never imports endpoint text or local source paths into the portable receipt, and it never contacts a provider.

Materialize the base packet before the Chai request. Its locked primary input must be the exact submitted multi-chain fold-input FASTA, because the adapter requires its manifest SHA-256 to equal the native receipt and observation fold-input hashes. The selected frozen plan and qualification stage must both use `route_kind: fal` and the same provider.

```bash
python3 <skill-directory>/scripts/normalize_biosymphony_chai_receipt.py normalize-stage \
  campaign-packet native-stage-root \
  native-stage-root/chai/candidate-001/seed-0007/inference-receipt.json \
  native-stage-root/cofold-observations.jsonl \
  normalized-chai-stage \
  --stage-id cofold-screen-chai \
  --candidate-id candidate-001 \
  --seed 7 \
  --json

python3 <skill-directory>/scripts/campaign_overlay.py import-stage \
  campaign-packet \
  normalized-chai-stage/companion-stage-receipt.json \
  companion-overlay \
  --artifact-root normalized-chai-stage \
  --json
```

The normalizer derives its portable receipt ID from the exact native inference-receipt bytes and selected observation-row bytes. It validates native output hashes before copying them and records cost as `unknown` rather than inferring a charge. As with every overlay, the resulting claim remains limited to `transport-proven` and does not independently verify provider execution or scientific validity.
