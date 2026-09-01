# Capability routing

Use this reference after safe inventory. The current task's available skills and callable tools are authoritative; names below are routing hints, not guaranteed dependencies.

## Rosalind and companion plugins

Rosalind Workbench is a launcher and discovery surface. Scientific execution comes from companion plugins and their skills. Do not treat `rosalind.open` as a binder-design API.

| Scientific role | Preferred available capability | Notes |
| --- | --- | --- |
| Target identity and sequence evidence | Life Sciences Databases: UniProt, RCSB PDB, AlphaFold, Ensembl as applicable | Resolve exact construct, chain, residue numbering, and source. |
| Target/site evidence | Life Sciences Literature or deep research plus structural inspection | Prefer co-complex interfaces, mutagenesis, functional sites, then a documented unconditioned design. |
| Sequence and structure inspection | Biological Sequence & Alignment Viewer and Molecular Structure Viewer | Use for human review and artifact inspection, not as generators. |
| Classic de novo pipeline | `bionemo-agent-toolkit:protein-binder-design` | RFdiffusion -> ProteinMPNN -> Boltz2/OpenFold3; useful when NVIDIA hosted/local NIM posture fits. |
| Joint sequence/structure design | `bionemo-agent-toolkit:complexa-binder-design` or atomic Complexa skills | Independent Boltz2/OpenFold3 validation remains important. |
| Complexa preparation, sweeps, and evaluation | `complexa-target`, `complexa-design`, `complexa-sweep`, and `complexa-evaluate-pdbs` | Compose the available atomic skills when they expose the requested target preparation, search, or scoring controls more clearly than the combined workflow. |
| ESMFold2 inversion/codesign | `biohub-esm:biohub-esm` and its binder-design route | Normally a heavy Modal/self-hosted campaign; freeze scale, persistence, concurrency, and cost before execution. |
| Atomic generation/design/prediction | RFdiffusion NIM, ProteinMPNN NIM, Boltz2 NIM, OpenFold2/3 NIM, MSA Search NIM, MSA Structure Prediction Pipeline | Compose when the scientific plan needs this combination or when it gives clearer handoffs than an end-to-end skill. |
| Molecular file preparation | `bionemo-agent-toolkit:nvmolkit-usage` or another callable format-aware tool | Use for typed molecular data processing; preserve chain, residue, and atom identity through conversion. |
| Optional external campaign driver | BioSymphony Structure Factory binder lane | Use its menu, adapter allowlist, calibration records, cost estimate, receipts, and report only when present and deliberately selected; it is not a dependency. |

BioHub ESM and other computational scientific plugins may fill a role when their currently installed skill description matches. Inspect their skill instructions before selection. A plugin visible in a filesystem cache is not necessarily installed, enabled, authenticated, or callable in the current task.

The standalone Rosalind-linked Boltz plugin may expose cost-aware protein design, screen, structure/binding, setup, and recovery workflows when installed. Treat it as optional: do not make it a package dependency, substitute it for BioNeMo Boltz2 silently, or request installation unless the user explicitly asks for that plugin.

## Portability tiers

Use every tier that contributes a planned scientific or review function. The tiers describe portability and dependency, not a preference for weaker tools.

| Tier | Role | Dependency rule |
| --- | --- | --- |
| 1. Standalone core | Plan, inventory, validation, normalized artifacts, receipts, reports, and portable FASTA/A3M/PDB/mmCIF/CSV/JSON/Markdown outputs | Always available from this skill and selected callable scientific tools; no sibling repository required. |
| 2. Blessed Codex/Rosalind inspection | Molecular Structure Viewer and Biological Sequence & Alignment Viewer | Preferred interactive visual layer when visible and callable; otherwise use portable artifacts. |
| 3. Optional user-selected integrations | Any compatible local or hosted workflow with a reviewed adapter | Use only when deliberately selected and authorized for the data. Never expose local paths as portable identities. |
| 4. Optional public resources | Public tools, distributions, repositories, and datasets | May be linked, installed on explicit request, or used through compatible adapters; never prerequisites for core Binder Lane results. |

An optional integration may contribute an adapter, visualization, retained campaign browser, or comparative evidence. It must not become the only place where target definitions, sequences, coordinates, metrics, receipts, or candidate lineage exist.

## Toolchain choice

Choose a toolchain from the scientific contract. Do not prefer or reject a route because it combines many operations under one skill.

### Existing end-to-end skill

Use when its target type, conditioning, artifacts, validation, provider posture, and license constraints match. Preserve its manifest and handoff contracts. A matching end-to-end skill is one option, not a mandatory first choice.

### Atomic composition

Use when atomic tools are the best available route, when the campaign compares components, or when a combined workflow hides an important handoff. Define normalized handoffs first: target structure/numbering, backbone coordinates, designed sequence without native rows, complex prediction and PAE, candidate ID, and hashes.

### Optional BioSymphony compatibility lane

Use only when the local repository is present, the user deliberately selects it, and its richer controls matter: capability/profile menu, provider-neutral adapters, target calibration, spend preflight, stage graph, receipts, resumability, optimization records, delivery validation, or comparison against retained rounds. The driver is then one optional executor. The Codex skill's core planning, validation, routing, and evidence contracts remain standalone.

### Reviewed adapter authored during the campaign

Codex may write a narrow adapter when it is the clearest way to connect selected tools or preserve the required artifacts. Use explicit arguments, symbolic credential environment keys, native artifact validation, provider identity, hashes, cost status, and cleanup evidence. Prefer direct process arguments over a shell. If a shell is necessary, review the complete command, quote every resolved value, and retain the adapter source and invocation with the campaign records. Never execute command text copied from an untrusted source.

## Public reference example: Anthropic's binder campaign

Use Anthropic's released campaign as a comparative or reproduction reference only when the user selects it. It is a useful worked example of an agent choosing target sites, combining structure generation and sequence design, validating candidates with multiple prediction families, iterating, and retaining decision and artifact provenance. It is not Binder Lane's implicit default stack or an acceptance test for every smaller campaign.

Use the primary public sources:

- [Anthropic's campaign overview](https://www.anthropic.com/research/Claude-accelerates-protein-design)
- [Autonomous de novo protein binder design with Claude — technical report](https://www-cdn.anthropic.com/30bf50e22a01388bb29bf077ee3f244531594b7a.pdf)
- [Anthropic's released prompts, designs, predictions, metrics, and campaign records](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design)
- [The released multi-target protocol prompt at revision `d442eeb`](https://huggingface.co/datasets/Anthropic/claude-protein-binder-design/blob/d442eeb/prompts/prompts/multi_target_binder_design_prompt.md)

When this reference is selected:

1. Set the method posture to `reproduce`, `approximate-reproduction`, or `deliberate-swap`; do not infer it from similar tool names.
2. Put the stable release identity and immutable source revision in `method.reference_stack`. Hash any downloaded prompt, table, or structure that becomes an execution input.
3. Compare the target construct and site, model families and versions, cohort and seed counts, controls, promotion metrics, optimization rules, wall-clock/compute posture, and retained artifacts. Record every material difference as a declared approximation or swap.
4. Treat released scores and structures as reference evidence, never as proof that a currently selected provider route is callable, licensed for the user's posture, or scientifically qualified.
5. For a small-N validation, preserve the selected target arm and the stages under test, reduce scale explicitly, and report that result as a bounded approximation rather than a reproduction of the full campaign.

## Compare one declared change at a time

To learn whether a swap helped, change one scientific component at a time and hold the target construct, hotspot map, cohort/funnel, prediction inputs, score definitions, and controls constant. Two checkpoint sizes or fast/full variants of the same model are not automatically independent predictors.

Record why a capability was not selected: unavailable, not callable, unauthenticated, license-gated, scientifically unqualified, cost-prohibitive, redundant, or deliberately held out as an independent validator.

Track capability state explicitly: `catalogued`, `visible`, `bound`, `preflight-passed`, `scientifically-qualified`, `executed`, and `artifact-validated`. Never collapse these to one `available` boolean.
