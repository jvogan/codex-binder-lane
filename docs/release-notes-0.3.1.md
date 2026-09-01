# Codex Binder Lane 0.3.1

Codex Binder Lane 0.3.1 is a submission-packaging and metadata update. The scientific workflow, authorization gates, and evidence boundaries are unchanged from 0.3.0.

## Changes

- Package the public submission as a full plugin ZIP with `.codex-plugin/plugin.json` at the archive root.
- Shorten the public subtitle to `Plan protein binder campaigns` (29 characters).
- Replace the starter prompts with three plain-English examples covering campaign planning, candidate review, and final reporting; every prompt is 128 characters or fewer.
- Keep the plugin skills-only, with no MCP server, hosted account, bundled model, or provider executor.

## Validation boundary

The release gate verifies the manifest and skill metadata, exact public file inventory, ZIP paths, plugin assets, direct and indirect discovery metadata, and five positive plus three negative activation tests. The bundled Python tests and local workflows make no scientific-provider call.

The intended source tag is `v0.3.1`.
