# Codex Binder Lane 0.2.1

Codex Binder Lane 0.2.1 improves the cold start, makes capability discovery safer, and closes a paid-compute authorization bypass while preserving the schema-v1 `plan-only` boundary.

The plugin manifest version is `0.2.1+codex.20260831011649`. The public source tag is `v0.2.1`.

## Added

- `init_campaign.py` creates a campaign-specific plan, selected qualification profile, target-lock template, and residue-map template in one new directory without provider calls.
- A target/site lock reference documents the exact schema, artifact-root behavior, chain and residue mapping, hashes, byte counts, and claim boundary.
- Codex discovery metadata and README prompts explain when to invoke Binder Lane, what it produces, and where companion execution begins.
- Release-surface checks cover the skill name, task-oriented description, explicit default prompt, and implicit invocation policy.

## Changed

- Default capability inventory no longer executes code from automatically discovered optional repositories. One deliberately selected BioSymphony root can be probed only through an explicit option after its instructions are reviewed.
- Positive stage or campaign estimates now derive a paid-compute authorization requirement. A stage cannot hide positive cost behind `paid=false`.
- A zero-dollar ceiling is valid for a fully bound, explicitly non-paid execute plan; potentially paid, unknown, unpriced, or malformed pricing declarations remain blocked.
- Plugin and skill descriptions now present Binder Lane as a campaign planning and validation control plane, while explicitly stating that schema-v1 packets do not dispatch.
- The campaign plan template exposes the target-lock artifact reference required by packet materialization.

## Evidence and execution boundary

Qualification schema v1 still has no hashed references to its supporting qualification records. Every v1 packet therefore remains dispatch-blocked, and the materializer ceiling remains `plan-only`. This maintenance release does not add a provider executor, runtime overlay, generic external-stage receipt importer, generated binder, or binding claim.

The synthetic canary remains software-only at `transport-proven`. The locked 1ZVH path remains local evaluation-only and does not generate, predict, or rank a binder.

## Verification boundary

On every Python version from 3.10 through 3.14, the release gate passes 109 source tests, 99 shipped plugin tests, and 6 public-surface tests, then compiles the Python sources. It also validates the Codex plugin and skill metadata, runs Ruff lint and changed-file formatting checks, checks relative links and whitespace, scans both repository histories and worktrees for leaked secrets, confirms all 40 installed files without drift, and compares two independently generated public exports containing 53 receipted files plus the receipt byte-for-byte. A fresh 29-file synthetic transport canary also materializes and validates at a `transport-proven` ceiling. These checks make no campaign-provider call and cost `$0.00`.

Publication to GitHub, clean-machine installation from the remote tag, and hosted CI remain separate release operations. Selected computational companion skills own provider-backed execution.
