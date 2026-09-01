# Changelog

This file records user-visible Codex Binder Lane changes.

## [Unreleased]

## [0.3.3] - 2026-09-01

### Changed

- Rewrite the public description, subtitle, and starter prompts around user outcomes: designing binders for a chosen site, comparing tools and costs, reviewing candidates, and organizing final results.
- Remove internal implementation language such as execution receipts from the public listing copy.

## [0.3.2] - 2026-09-01

### Fixed

- Remove the unsupported `metadata` interface block from `SKILL.md`; all supported skill interface settings now live only under `interface` in `agents/openai.yaml`.

## [0.3.1] - 2026-09-01

### Changed

- Shorten the public subtitle to fit the submission portal's 30-character limit.
- Replace the three starter prompts with plain-English, outcome-focused examples that each fit the portal's 128-character limit.
- Publish the submission artifact as a full plugin ZIP with `.codex-plugin/plugin.json` at the archive root.

## [0.3.0] - 2026-09-01

### Added

- Add public privacy and terms documents, directory logo assets, and submission-ready activation tests.
- Add install-surface legal links, brand color, logo, and composer icon to the plugin manifest.
- Import and verify one strict companion-stage receipt plus its declared outputs in a separate immutable overlay bound to an exact base packet.
- Reject receipt/base drift, output tampering, unsafe paths, symlinks, secret-like values, and private endpoints without mutating the packet.
- Add Anthropic's official campaign overview, technical report, released dataset, and pinned multi-target protocol prompt as an opt-in comparative or reproduction reference.
- Add a versioned delivery index that requires every scoped candidate's full sequence and FASTA file, site-aware metrics, target–binder coordinates, a browser-captured white-background structure view with the exact target site highlighted, and a real embedded video when requested.
- Add explicit stage IDs, combined-capability coverage, manual handoff routes, and configurable artifact budgets for multi-tool campaigns.
- Add a `custom-campaign` scope for site discovery, deliberate partial workflows, tool comparisons, and reruns that do not need the complete default funnel.

### Changed

- Promote the release candidate to the stable `0.3.0` plugin identity and tune discovery metadata against direct, indirect, and negative prompts.
- Keep the base packet dispatch-blocked at `plan-only`; the overlay can claim at most `transport-proven` and does not independently verify provider execution or scientific quality.
- Assign the unreleased overlay checkpoint a distinct `0.3.0-rc.1` plugin identity rather than reusing the published `0.2.1` build identity.
- Lock HTML, sequence, structure, video, browser-verification, and candidate-scope requirements in execute plans before compute begins.
- Treat `plan-only` as the base packet's claim ceiling, not as a reason to stop an authorized campaign before invoking its selected companion tools.
- Allow one stage to cover several declared campaign functions while still requiring a complete generation-to-delivery funnel.
- Reject silent weakening of selected models, checkpoints, precision, sampling, seeds, or hardware.
- Let Codex author reviewed workspace adapters and substitute compatible tools when a preferred integration is unavailable.
- Describe report hygiene and release provenance in portable, repository-neutral language.
- Check the release tree for generic personal-home and workspace-directory paths without embedding a maintainer's local identifiers.
- Put the standalone requirements and optional Codex/Rosalind companion routes beside the installation instructions.
- Sharpen the public positioning around Binder Lane's provider-neutral control and evidence role, align its discovery descriptions, and add pinned-release update and Rosalind Workbench quick-start guidance.
- State plainly that per-stage verification and presentation validation do not replace whole-campaign reconciliation.

### Fixed

- Require finite numeric site metrics and verify that delivered PDB/mmCIF files contain the declared target chain, binder chain, and locked target-site residues.
- Keep manifest starter prompts within Codex's 128-character UI limit and verify the shipped public manifest.
- Prevent a hash-complete archive, handoff packet, coordinate file, or storyboard from being reported as a completed user-facing visual delivery.
- Keep computational closeout and presentation closeout separate so a correct stop condition cannot hide missing report artifacts.
- Prevent generic structure thumbnails, unbound screenshots, missing captions, future storyboards, or coordinate downloads from satisfying the target-site visual handoff.
- Reject execution plans that leave the target site as unconstrained discovery; planning may explore sites, but execution must lock one.

## [0.2.1] - 2026-08-30

### Added

- Initialize campaign-specific plan, qualification, target-lock, and residue-map starters with one provider-free command.
- Document the exact target/site lock and residue-map contract.
- Validate the metadata used for explicit and implicit Codex skill discovery.

### Fixed

- Stop safe discovery from executing code in automatically discovered optional repositories.
- Reject positive-cost execute stages that claim `paid=false` and require paid authorization for any positive stage or campaign estimate.
- Permit a zero-dollar ceiling only for fully bound, explicitly non-paid execution, and reject malformed unpriced-work declarations.

### Changed

- Clarify the difference between Binder Lane's local control-plane capabilities and separately authorized companion execution.
- Expose the target-lock reference in the campaign plan template.
- Keep every qualification-schema-v1 packet dispatch-blocked at `plan-only`.

## [0.2.0] - 2026-08-30

### Added

- Validate hashed target artifacts, chain mappings, residue maps, and site residues.
- Validate capability identity, revision, license, route, egress, price, artifact type, and ordered evidence states.
- Materialize and verify deterministic packets with source contracts, status, stage graph, receipt, report, manifest, and manifest hash.
- Provide plan-only qualification profiles for the classic RFdiffusion/ProteinMPNN route and the Complexa holo/apo route.
- Provide local synthetic-transport and public deposited-complex evaluation paths.
- Distribute the plugin through a versioned Codex marketplace repository with a deterministic public-export receipt.

### Changed

- Require Python 3.10 or later and test Python 3.10 through 3.14.
- Keep every qualification-schema-v1 packet dispatch-blocked at a `plan-only` materializer claim ceiling.
