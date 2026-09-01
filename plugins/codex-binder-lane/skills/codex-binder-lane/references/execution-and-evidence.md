# Execution and evidence

Read this reference before a live or provider-backed campaign.

## Wave 0: free contract work

1. Inventory current-task skills, callable tools, repository adapters, local executables, and credential *presence* without exposing values.
2. Resolve target/construct/site and write the plan contract.
3. Inspect licenses, weight terms, provider/data restrictions, and target confidentiality.
4. Run tool-specific static preflight and a dry run. Validate expected fanout and artifact paths.
5. Present the estimate, unpriced work, ceiling, and exact live boundary.

## Wave 1: technical canaries

Use the smallest scientifically harmless, public-safe input that establishes runtime, model identity, request/response shape, artifact export, hashes, cost reporting, and cleanup. A canary tests transport and carries `transport-proven` as its maximum claim.

Apply the retry and fanout budget in the plan. A bounded retry for a diagnosed transient failure is valid when it fits that budget; blind retries are not. Do not silently change GPU type, provider, model, checkpoint, sampling depth, or precision after a failure.

## Wave 2: calibrated pilot

Run positive and negative controls through the same preparation, predictor, and scoring path as candidates. Verify target numbering and hotspot contacts from coordinates. Use an initial funnel small enough that failed handoffs or unqualified metrics do not multiply into expensive cofold calls.

If controls do not separate, do not rank candidates on that metric. Repair conditioning, predictor inputs, or calibration; otherwise publish an unranked pilot.

## Wave 3: bounded campaign and optimization

Expand only after prior artifacts validate. Every candidate keeps a stable ID and lineage across generation, sequence design, prediction, scoring, promotion, and optimization. Apply diversity caps before promotion so one backbone or sequence family cannot occupy the full shortlist.

An optimization round records parents, mutating operator, children, evaluation inputs, primary-metric delta, diversity effect, cost, stop decision, and next-round rationale. Re-score finalists with the declared seed/predictor panel rather than comparing results from mismatched evaluation budgets.

## Required receipts

For each stage retain:

- stage and adapter/capability ID;
- target, candidate, parent, and child IDs;
- input, contract, source, model/checkpoint, environment, and output hashes;
- provider/deployment and request/job identity;
- timestamps and state transitions;
- parameters and seeds;
- expected, produced, parsed, valid, passed, and promoted counts;
- metrics with source and units;
- observed cost, estimate, or `unknown` status;
- artifact fetch and independent validation result;
- cleanup state for paid ephemeral resources;
- failure and retry history.

Never put secrets, private structures, unpublished sequences, or credential-bearing URLs in a tracked plan or receipt.

## Respond to failures

Stop when the next action would exceed authorization, transfer protected data without permission, exceed the budget, use an ambiguous target identity that changes conditioning, or accept mismatched or invalid artifacts. For an unsupported molecule type, missing template, unavailable tool, or adapter mismatch, select another compatible capability or repair the adapter within the approved scope. Preserve partial artifacts with a truthful `partial`, `blocked`, or `failed` closeout.

Provider success establishes transport. A parsed coordinate file establishes artifact shape. Model confidence plus calibrated controls supports the declared computational ranking.
