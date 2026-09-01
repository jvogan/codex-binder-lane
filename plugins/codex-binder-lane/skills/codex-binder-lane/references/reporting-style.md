# Reporting style contract

Use this contract for Binder Lane Markdown reports and their machine-readable summaries. Reports present checkable results, their scope, and the files that support them.

## Lead with scoped facts

Use this heading order when the sections apply:

1. identity and outcome;
2. counts and their semantics;
3. evidence boundary;
4. review and media handoffs;
5. integrity evidence, cost, cleanup, and failures.

Name the scope of every status. Prefer `bundle assembly: materialized`, `viewer capability: unprobed`, and `invocation: not run` over an unqualified `completed` or `available`. A report created before final bundle validation must not self-assert that validation passed; point to the validator result and manifest evidence instead.

Keep computational closeout and presentation closeout separate. A campaign may have correctly stopped at a scientific or budget gate while its promised report is still missing visible sequences, renders, video, or browser verification. In that case, state the computational outcome and `presentation delivery: incomplete`; do not summarize the whole campaign as completed.

State one overall claim ceiling near the top. When artifact ceilings differ, add one scoped evidence table that distinguishes the immutable base packet from later overlays; do not paraphrase either ceiling as a stronger success claim later.

## Keep Markdown and JSON in parity

Every user-facing summary fact must have one Markdown representation: campaign and candidate IDs, fixture/campaign kind, count semantics and counts, ranking status, missing measurements, cost, cleanup, and per-surface handoff states. Schema versions and low-level hashes may remain JSON-only.

Render a missing metric as `Not measured`, never as zero, an empty cell, or a fabricated estimate. Explain nonstandard counts immediately before their table. For a transport canary, `passed` means transport shape/hash validation, not scientific promotion.

## Report handoffs as state, not implication

For each viewer, renderer, or video framework, distinguish:

- packet: `not-emitted` or `emitted`;
- runtime: `unprobed`, `available`, or `unavailable`;
- invocation: `not-run`, `attempted`, `completed`, or `failed`;
- output validation: `not-run`, `pending`, `passed`, or `failed`, with the output count and manifest-backed references.

These are the exact machine values. Human-facing prose may replace hyphens with spaces, but the report's JSON summary must retain the enums above.

An emitted handoff does not mean the tool opened, reviewed, rendered, or validated anything. Requested review checks are instructions, not completed findings.

## Use precise language

Avoid vague claims such as `proves shape`, `robust`, `comprehensive`, `seamless`, `leverages`, or `various`. Name the exact artifact or check instead. Avoid repeating the same evidence boundary in prose and standalone lines; use a compact table when several null or negative facts belong together.

Keep tables narrow. Prefer a two-column stage/count table to a seven-column funnel table. Precede each table with a sentence that defines what its values mean.

Write for the report reader. Lead each section with its conclusion, use direct verbs, define a technical term once, and keep method detail next to the result it qualifies. Prefer one concrete sentence over a paragraph of process narration.

Reports contain the scientific inputs, execution provenance, results, and files needed to inspect them. Exclude credentials, machine-specific paths, cache locations, debugging notes, and private workspace details. Runtime, provider, model, version, request, cost, and artifact provenance remain appropriate when they support a result. Describe what ran, what it produced, and how it was checked.

## Golden-report gates

- deterministic Markdown bytes for deterministic fixtures;
- fixed heading order with no skipped levels;
- exactly one overall claim-ceiling statement, plus at most one scoped artifact-ceiling table when base and overlay ceilings differ;
- Markdown counts equal summary, metrics, and manifest counts;
- null scientific values render as `Not measured` and ranking renders as `Unranked`;
- all mentioned handoffs are inputs to the report receipt;
- closeout references all earlier receipts;
- no viewer, renderer, or video output is implied when invocation is `not-run`;
- no credential, machine-specific path, cache location, debugging note, or private workspace detail appears in the report;
- no claim exceeds the declared `claim_ceiling`.
- every candidate in the locked sequence scope has its full sequence visible in the HTML and a FASTA download;
- every candidate in the locked structure scope has raw coordinates and a real image render visible in the HTML;
- a requested video is a decoder-validated MP4/WebM embedded in the HTML; a storyboard is planning evidence only;
- the built HTML has browser evidence for overview, sequence, and structure sections, plus video playback when applicable;
- the curated delivery index excludes vendored repositories, examples, dependency trees, caches, and other archive-only material;
- overall `completed`, `done`, or `release ready` language appears only after computational and presentation closeout both pass.
