# Codex Binder Lane 0.3.0-rc.1

This release candidate adds immutable per-stage result packages, flexible campaign scopes, and a strict delivery contract to the Binder Lane control plane. Selected companion tools continue to own provider execution.

The plugin manifest version is `0.3.0-rc.1+codex.20260901154853`. The intended source tag is `v0.3.0-rc.1`.

## Added

- Import and verify one strict companion-stage receipt plus its declared outputs in a separate overlay bound to an exact base packet.
- Normalize one documented computational companion receipt shape into the strict overlay schema.
- Reject packet drift, output tampering, unsafe paths, symlinks, secret-like values, private endpoints, ambiguous JSON, and undeclared outputs.
- Preserve exact output hashes, byte counts, request identity, provider identity, status, observed cost, and result ceiling.
- Cite Anthropic's official campaign overview, technical report, released dataset, and pinned protocol prompt as an opt-in reference stack, with explicit reproduction, approximation, and swap rules.
- Lock report, visible-sequence, structure-visual, video, browser-verification, and candidate-scope requirements in execute plans.
- Validate a versioned delivery index so each scoped candidate has its full sequence and FASTA file, site-aware metrics, target–binder coordinates, and a browser-captured white-background view that shows the complete target, the binder, and the exact highlighted site.
- Require visible captions and hash-bound render recipes; raw coordinates cannot stand in for renders, storyboards cannot stand in for video, and exhaustive archives cannot stand in for user-facing delivery.
- Require a decoder-valid embedded movie, playback evidence, and a hash-bound candidate/scene storyboard whenever video is requested.
- Reject duplicate JSON keys and non-finite values across the core plan, lock, qualification, and packet readers.
- Reject plugin source/destination symlink escapes and undeclared symlinked install entries; reject public text containing credential headers, common escaped credential keys, file URIs, UNC paths, or undeclared FASTA-like content; and require an exact, non-symlinked delivery inventory.
- Require a terminal cleanup state without inferring provider lifecycle evidence; hosted Chai truthfully records cleanup as not applicable. Decode PNG pixels, reject active or externally loading SVG content, fully decode JPEG/WebP with local `ffmpeg`, and require `ffprobe` metadata plus a full `ffmpeg` decode for MP4/WebM instead of accepting magic prefixes.
- Classify dry-run and execute plans as full campaigns, custom campaigns, technical canaries, or deposited-complex evaluations. Full campaigns declare the complete logical funnel; custom campaigns record a deliberate subset.
- Support explicit stage IDs, combined-capability stages, manual handoffs, and configurable artifact budgets without weakening the required full-campaign coverage.
- Let Codex author and retain narrow reviewed adapters when no existing adapter cleanly connects the selected tools.
- Permit a custom site-discovery campaign to select and record a site; require the resulting concrete site lock before a full generation campaign.
- Reject silent changes to selected models, checkpoints, precision, sampling, seeds, or hardware.
- Keep default capability inventory static; Codex CLI and selected-checkout probes are explicit opt-ins.

## Boundary

The base schema-v1 packet remains immutable, dispatch-blocked, and `plan-only`. A completed overlay can claim at most `transport-proven`; it proves that the normalized receipt and copied artifacts are bound to the packet, not that Binder Lane dispatched the work or independently established scientific quality.

`plan-only` is the packet materializer's ceiling. It does not prevent a separately selected computational companion from running under the frozen execute authorization recorded in the plan and qualification ledger.

## Verification

| Check | Local verification | Release operation still pending |
| --- | --- | --- |
| Source tests | 181 passed locally on Python 3.10–3.14 | Hosted Python 3.10–3.14 matrix on the exact tag |
| Declared plugin surface | 51 files synchronized and checked in a temporary destination | Fresh-profile installation and task discovery |
| Generated public tree | 68 receipted files; two exports byte-identical | Tag and publish the reviewed tree |
| Generated-tree tests | 7 public-surface and 169 shipped plugin tests passed | Repeat on the exact tag and release archive |
| Python compilation | Source and generated-tree compilation passed | Repeat in hosted matrix |

The source suite exercises packet materialization, overlay normalization and import, exact-file verification, deterministic IDs, base immutability, cost binding, path portability, size limits, secret rejection, decoder-backed media checks, terminal cleanup reporting, and tamper detection. The release tree is generated from an explicit allowlist and sealed with a SHA-256 receipt. Its bundled verifier establishes receipt and file-set self-consistency; trusted provenance comes from regenerating the allowlisted tree from the declared source revision and comparing the result byte-for-byte.

Publication of the intended tag, hosted CI on that tag, and a fresh-profile Codex installation remain release operations to perform after local verification passes.
