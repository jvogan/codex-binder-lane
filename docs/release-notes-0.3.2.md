# Codex Binder Lane 0.3.2

Codex Binder Lane 0.3.2 is a submission-compatibility update. The scientific workflow, authorization gates, and evidence boundaries are unchanged from 0.3.0.

## Fix

- Remove the unsupported `metadata` interface block from `skills/codex-binder-lane/SKILL.md`.
- Keep the supported display name, 29-character subtitle, and 128-character explicit default prompt under `interface` in `skills/codex-binder-lane/agents/openai.yaml`.
- Retain `.codex-plugin/plugin.json` at the archive root and the three 128-character-or-fewer public starter prompts in the plugin manifest.

## Validation boundary

The release gate verifies the manifest and skill metadata, exact public file inventory, ZIP paths, plugin assets, direct and indirect discovery metadata, and five positive plus three negative activation tests. The bundled Python tests and local workflows make no scientific-provider call.

The intended source tag is `v0.3.2`.
