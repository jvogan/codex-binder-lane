# Campaign plan contract

Use this reference when drafting or reviewing `codex-binder-plan.json`. The JSON is a decision and audit contract, not an executor-specific command file.

## Required decisions

The plan must record:

- `campaign_id` and `mode`: `plan`, `dry-run`, or `execute`;
- purpose, intended use, safety assessment, commercial posture, and private-data status;
- target identity, construct, source, chain mapping, confidentiality, and site/hotspot residues with numbering scheme and evidence;
- binder modality, length range, desired delivered count, and forbidden or fixed sequence features;
- method posture: `reproduce`, `approximate-reproduction`, `deliberate-swap`, or `best-available`, plus any reference stack and declared substitutions;
- execution scope (`full-campaign`, `custom-campaign`, `technical-canary`, or `deposited-complex-evaluation`), posture, and selected provider/tool capability for each stage;
- a stable `stage_id` for each stage when more than one stage shares a scientific role; older plans may omit it and use `role` as the stage identity;
- a closed `route_kind` for each stage, separate from its provider identity; remote
  route kinds include hosted APIs, FAL, Modal, RunPod, Lambda, AWS, SSH/HPC,
  external adapters, and reviewed manual handoffs, all of which trigger the same
  private-egress gate;
- explicit per-overlay file, aggregate-byte, and per-artifact budgets. Split a large stage result into separately imported, hash-bound sibling overlays instead of raising the in-memory byte ceiling;
- budget ceiling, wall-clock cap, cost-estimate status, and explicit authorization booleans;
- initial cohort and funnel counts, bounded optimization settings, and stop conditions;
- one primary metric with `maximize` or `minimize`, calibration status, secondary metrics, diversity constraints, and controls;
- expected artifacts, evidence requirements, claim ceiling, and unresolved blockers.
- preferred structure/sequence review surfaces plus portable fallbacks; a viewer may be `preferred`, `required-by-user`, or `not-requested`, but it is never an implicit scientific gate.

Start from `assets/codex-binder-plan.template.json`. Replace every `null` that controls spend, biology, or scientific interpretation before live execution.

`unconstrained-discovery` is valid during planning and in a `custom-campaign` that selects a site. The site-discovery campaign emits its selected residues, numbering, evidence, and source hashes. Before a full generation campaign, create a new plan and target/site lock from that result. Other dry-run and execute scopes require a concrete residue, reference-interface, pose-derived, or spatial-patch site.

A `full-campaign` scope declares the full logical funnel, or one selected capability whose role is `end-to-end-binder-design`. A combined tool can keep its own role name and list the logical stages in `covers`. Valid coverage values are `target-site-preparation`, `generation-or-codesign`, `independent-complex-prediction`, `interface-and-control-scoring`, `diversity-novelty-developability`, `promotion`, and `final-report`.

Use `custom-campaign` for a deliberate subset, such as one tool comparison, a prediction-only rerun, or a campaign that omits a stage the user does not need. Record the selected stages, expected outputs, omissions, and claim scope. `technical-canary` and `deposited-complex-evaluation` retain their narrower meanings.

## Method-posture semantics

- `reproduce`: preserve the named scientific components, versions or model families, conditioning, controls, and metric definitions. Provider transport may change only if the plan says it is not scientifically material and records the change.
- `approximate-reproduction`: preserve the reference workflow's scientific intent while explicitly recording every unavailable, unverified, or deliberately approximated component. Never report this posture as an exact reproduction.
- `deliberate-swap`: name every changed component and the hypothesis for the swap. Keep the rest fixed when comparison is the goal.
- `best-available`: choose from capabilities actually callable in the current task, with an explicit reason per stage and a fallback.

For any named reference stack, `method.reference_stack` must identify a stable public release, immutable revision, DOI, or equivalent source locator; a bare project name is not enough for a reproduction claim. Hash each downloaded prompt, configuration, table, sequence, or coordinate file that becomes an execution input. If only a mutable source is available, freeze a dated snapshot and use `approximate-reproduction` until its identity can be verified.

## Metric semantics

The primary metric controls promotion. It must not be a vague composite such as “best binder.” Record its source, direction, aggregation across seeds/predictors, target-specific gate or calibration plan, and tie-breaker. Common supporting metrics include interface confidence, ipSAE, interface PAE, binder/complex confidence, self-consistency RMSD, hotspot-contact fraction, clashes, novelty, solubility, aggregation risk, and sequence diversity.

Do not optimize a metric produced only by the generator and call that independent validation. Do not use ligand-affinity outputs to rank protein-protein binders unless the tool explicitly defines and validates that use.

## Round semantics

Record initial candidates, backbones, sequences per backbone, shortlist size, parents, variants per parent, prediction seeds, and final rescore seeds. Each optimization round must bind a mutating operator or a new hypothesis. If the operator is identity/no-op, set rounds to zero or label the steps as repeated measurement, not optimization.

Useful stop conditions are:

- primary metric reaches a calibrated target while controls remain separated;
- improvement falls below a declared delta for a declared number of rounds;
- no candidates pass a required gate;
- diversity collapses below its floor;
- budget or wall-clock ceiling is reached;
- required artifact, control, provenance, or cleanup evidence is missing;
- maximum rounds is reached.

## Authorization semantics

`maximum_spend_usd` is the campaign ceiling, but it does not technically cap a provider unless an executor enforces it. Record estimate confidence and unpriced work. `paid_compute_authorized`, `private_data_authorized`, and `restricted_license_authorized` are independent gates; one never implies another. Never record credentials or secret values.

For execute mode, lock the target source and normalized input hashes, chain map,
residue-map artifact/hash, exact provider and route kind, per-stage estimate, total
estimate, wall-clock ceiling, declared evaluation fanout, and mandatory stop rules.
Provider names never double as route kinds, and a route declaration never proves
authentication, scientific qualification, or artifact validation.

Binder Lane records computational artifacts and computational claim ceilings. Other workflows are outside this skill.

## Claim ceilings

- `plan-only`: this artifact carries planning and validation evidence only. A frozen base packet keeps this ceiling even when later evidence is retained separately.
- `transport-proven`: declared receipt and output bytes passed integrity and transport checks. This alone does not establish who executed the stage or scientific validity.
- `computational-candidate`: one model family produced a candidate with traceable artifacts.
- `cross-model-supported`: two independent model families and target-matched controls support the computational ranking.

Qualification-ledger v1 cannot bind the independent model-family evidence needed for `cross-model-supported`, so a schema-v1 packet cannot claim that ceiling. A campaign report can use the phrase only when it cites two independent predictor families, target-matched control results, exact native receipts, and result hashes as separate evidence.
