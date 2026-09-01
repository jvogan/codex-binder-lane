# Target/site lock contract

Use a target/site lock to bind one campaign to exact local target artifacts, chain identities, residue numbering, and a reviewed site. The lock is an input-integrity record. It does not prove transport, prediction quality, or binding.

Run `scripts/init_campaign.py` to create `target-site-lock.template.json` and `residue-map.template.csv`. Complete both templates, rename the lock to `target-site-lock.json`, and validate it before packet materialization. Then seal the finished lock's path, SHA-256, and byte count into `plan.target.target_lock`, seal the residue-map path and SHA-256 into `plan.target.residue_map`, and re-run the plan validator.

## Required lock fields

The JSON root must use `schema_version: codex-binder-target-site-lock/v1` and contain only:

- `campaign_id`: the same portable identifier used by the plan and qualification ledger.
- `target_id`: the exact identifier used by `plan.target.identifier`.
- `confidentiality`: `public`, `private`, or `restricted`.
- `source_lock`: `source_id`, `source_version`, SHA-256, and byte count for both the source record and normalized primary input.
- `primary_input`: safe relative POSIX `path`, lowercase `sha256`, and positive `size_bytes`.
- `chains`: one or more `source_chain_id`, `campaign_chain_id`, and `role` mappings. At least one role must be `target`; allowed roles are `target`, `binder`, `context`, and `partner`.
- `residue_map`: safe relative POSIX `path`, lowercase `sha256`, and positive `size_bytes`.
- `site`: `site_id`, `mode`, `numbering_scheme`, non-empty `residues`, and explicit `evidence`.
- `claim_ceiling`: normally `plan-only`. `transport-proven` is only a software-transport claim and never a scientific claim.

The optional `fixture_kind` and `non_biological` fields must appear together. Do not label biological target data as a non-biological fixture.

## Residue map

The CSV header must include these exact fields:

```csv
source_chain_id,author_residue_number,insertion_code,campaign_chain_id,campaign_residue_number
```

Optional fields are `residue_name` and `meaning`. Each site residue must match one exact CSV row. Author residue numbers are integer strings; insertion codes are empty or one uppercase alphanumeric character; campaign residue numbers are positive integers.

Supported locked site modes are `explicit-residues`, `reference-interface`, `pose-derived`, and `spatial-patch`. An `unconstrained-discovery` plan is a planning posture, not a packet-ready lock: select and review an explicit site before materialization.

## Artifact hashes

Artifact paths are relative to `--artifact-root`. The validator rejects absolute paths, traversal, backslashes, symlinks, changed byte counts, changed hashes, missing files, and unknown JSON fields.

Use Python to compute an artifact reference without exposing its contents:

```bash
python3 -c 'import hashlib,json,pathlib,sys; p=pathlib.Path(sys.argv[1]); b=p.read_bytes(); print(json.dumps({"path":sys.argv[2],"sha256":hashlib.sha256(b).hexdigest(),"size_bytes":len(b)},sort_keys=True))' INPUT_FILE RELATIVE_PATH
```

The normalized primary input reference must exactly match `source_lock.input_sha256` and `source_lock.input_size_bytes`. `source_lock.source_sha256` and `source_lock.source_size_bytes` identify the upstream source bytes even when only a normalized derivative is retained locally.

## Validate

```bash
python3 <skill-directory>/scripts/validate_target_site.py \
  target-site-lock.json \
  --artifact-root ARTIFACT_ROOT
```

Validation is local and read-only. A passing lock establishes identity and artifact integrity only. Qualification and schema-v1 dispatch blockers remain separate.
