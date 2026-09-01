# Fixed PyMOL snapshot adapter

Use `scripts/render_locked_pymol_snapshot.py` only for the sealed public 1ZVH assembly described in [the deposited-complex example](public-deposited-complex.md). The adapter is local-only and accepts no PML, Python, selection, color, camera, or shell input from the caller.

```bash
python3 scripts/render_locked_pymol_snapshot.py 1zvh.cif ./empty-output
```

The adapter requires the exact locked CIF size and SHA-256, resolves the allowlisted `pymol` executable, records its detected version, and invokes a fixed scene definition. It renders the full complex as cartoon, colors label-asym target A cyan and label-asym VHH B magenta, adds residues within 4.0 Å as sticks, uses a dark background, and disables ray tracing and antialiasing for a stable technical snapshot.

Success requires a zero process exit, a regular non-symlink PNG with a valid signature, bounded chunks and CRCs, nonempty IDAT, terminal IEND, exact 1280×720 dimensions, and a receipt containing source and output hashes and byte counts. Failure removes partial PNG and receipt files.

The receipt's evidence class is `deposited-visualization` and its claim ceiling is `transport-proven`. A rendered interface view is not evidence of affinity, specificity, stability, efficacy, or successful binder design.

ChimeraX is a separate runtime and adapter. Do not label a PyMOL render as ChimeraX output or silently substitute it when ChimeraX is unavailable.
