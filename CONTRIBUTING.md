# Contributing

Codex Binder Lane accepts focused fixes to its validators, packet contracts, public fixtures, tests, and documentation.

## Prepare a change

1. Use Python 3.10 or later.
2. Keep runtime code in the Python standard library unless the change includes a documented dependency decision.
3. Preserve deterministic output, exact-file checks, bounded input reads, and explicit claim ceilings.
4. Keep credentials, provider account records, machine paths, unpublished biology, and generated campaign artifacts out of the repository.
5. Use synthetic non-biological fixtures or cited public deposited structures for tests. Do not commit raw coordinate assets from the locked 1ZVH workflow.

## Run the release checks

```bash
python3 scripts/verify_public_export.py
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s plugins/codex-binder-lane/tests -v
python3 -m compileall -q scripts tests plugins/codex-binder-lane
```

Add a test for each behavior change. Update the changelog when a reader or plugin user can observe the change.

## Scientific claims

Keep each claim within the evidence recorded by its artifacts. A schema-v1 base packet has a `plan-only` ceiling, a synthetic canary can reach `transport-proven`, and a campaign report cites later computational results separately.

## Public source process

The repository contains an allowlisted release tree. Maintainers apply accepted changes to the canonical source, regenerate the release tree, and verify its receipt before the next release.
