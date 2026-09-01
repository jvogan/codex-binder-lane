# Codex Binder Lane 0.3.0

Codex Binder Lane 0.3.0 is the first stable release of the provider-neutral control and evidence layer for protein-binder campaigns in Codex. It plans and locks campaign intent, coordinates separately authorized companion tools, validates immutable result packages, and delivers reviewable sequences, metrics, structures, visuals, reports, and underlying evidence.

## Stable release additions

- Publish privacy and terms documents that describe local processing, separately authorized external routes, retention, user controls, scientific limitations, and third-party service boundaries.
- Add a production square logo, composer icon, brand color, and legal links to the plugin manifest.
- Tune the skill discovery description for direct Binder Lane requests, indirect multi-stage campaign requests, and explicit non-activation cases.
- Add five positive and three negative submission tests with reviewer-reproducible local fixtures and expected result shapes.
- Add a bundled valid dry-run plan fixture for an offline activation and validation test.

## Campaign and evidence features

- Initialize campaign-specific plan, qualification, target-lock, and residue-map starters without a provider call.
- Validate target identity, constructs, chains, residue maps, target sites, authorization, budgets, licenses, providers, routes, prices, artifacts, and evidence states.
- Materialize deterministic plan-only packets and import strict, hash-bound per-stage companion receipts into separate immutable overlays.
- Reject source or receipt drift, output tampering, unsafe paths, symlinks, secret-like values, private endpoints, ambiguous JSON, undeclared outputs, and non-finite metrics.
- Support full campaigns, custom campaigns, technical canaries, deposited-complex evaluations, combined-capability stages, manual handoffs, and bounded optimization rounds.
- Validate delivery packages containing scoped full sequences, site-aware metrics, target-binder coordinates, highlighted-site images, browser evidence, and real embedded video when requested.

## Scientific boundary

Binder Lane does not bundle model weights or independently run a scientific provider. Selected companion tools own generation, design, prediction, scoring, optimization, and rendering. Base schema-v1 packets remain `plan-only`; imported receipt overlays can establish at most `transport-proven`. Computational or cross-model claims require the additional native evidence and controls named in the skill.

## Verification

- Plugin manifest validation passes.
- The generated public tree and exact file inventory are protected by the checked-in SHA-256 receipt.
- Eight repository-surface tests and 169 shipped plugin tests pass locally on the release tree.
- Python sources compile on supported Python 3.10 through 3.14.
- Git secret scanning reports no leaks in the reviewed release history.

The intended source tag is `v0.3.0`.
