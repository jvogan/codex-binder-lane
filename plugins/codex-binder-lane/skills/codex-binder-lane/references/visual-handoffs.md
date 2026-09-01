# Visual and inspection handoffs

The first visual identifies the target, the requested site, and the binder. Interactive views support inspection, and the bundle retains portable source artifacts and stable identifiers for other viewers and scripts.

## Blessed Codex/Rosalind paths

Use these when they are visible and callable in the current task:

| Review need | Preferred capability | Minimum portable fallback |
| --- | --- | --- |
| Target construct, chains, site, and residue numbering | Molecular Structure Viewer (`structure-viewer:structure-viewer`) | PDB or mmCIF, residue map, site table, and source hash |
| Candidate complex, hotspot contacts, interface geometry, clashes, and confidence context | Molecular Structure Viewer (`structure-viewer:structure-viewer`) | Candidate PDB/mmCIF, metric table, contact table, provenance, and a readable report |
| Target, binder, and finalist sequences | Biological Sequence & Alignment Viewer (`sequence-viewer:biological-sequence-viewer`) | FASTA plus candidate table and sequence hashes |
| Alignment, diversity, annotations, constraints, and motif review | Biological Sequence & Alignment Viewer (`sequence-viewer:biological-sequence-viewer`) | FASTA/A3M or aligned FASTA, annotation table, diversity summary, and report |

Load the selected viewer's skill instructions before using it. Viewer availability is a presentation capability, not a scientific qualification state for generation or prediction.

## Mounted-viewer acceptance

A handoff file is not an interactive review. When a blessed viewer is callable, run the control path in the same conversation that owns the mounted viewer and preserve the returned session identity. Do not automate the embedded webview through browser or developer tools, and do not delegate control of that session to another agent.

For Structure Viewer:

1. Open the target or lead complex once and confirm the viewer is mounted, rendered, and loaded before reporting it as ready.
2. Use the returned `viewerSessionId` for every control. Before a revision-guarded scene or PyMOL-style mutation, read and pass the current scene revision.
3. Select or focus the locked target site by author chain, residue number, insertion code, and assembly instance. Keep the complete molecular context visible while adding site or interface representations.
4. For a finalist review, load or open the exact hash-bound candidate coordinates, apply consistent target/binder colors, and run the requested contact, clash, distance, buried-area, or comparison operation. Report the returned method, cutoffs, scope, and truncation.
5. Save a named scene when the review will continue. When source-relative publication is available, export SceneState JSON and at least one PNG with its render sidecar; add an MP4 only when motion explains a relationship that a still image does not.
6. Re-read live context after the final mutation and record the actual invocation and validation state. Never infer that a selection, scene, render, or measurement succeeded from the request alone.

For Biological Sequence & Alignment Viewer:

1. Open the candidate FASTA or alignment once and confirm the mounted document's live mode, records, and coordinate semantics.
2. Use its `viewerSessionId` to choose the exact target or candidate record, set the alignment reference when applicable, and select the designed region, constraint, motif, or comparison columns by 1-based coordinates.
3. Apply a molecule-compatible palette and the requested annotations or metric tracks, then query omitted rows, features, or metrics instead of guessing from a truncated context.
4. Run the requested diversity, statistics, alignment, or tree operation through the typed workbench and preserve its engine, parameters, scope, and limitations.
5. Save the viewer session for continued review. Export the relevant FASTA/alignment, annotations, SVG/table, Newick, or JSON artifact when publication is authorized, and record the actual invocation and validation state.

A release acceptance pass exercises both mounted viewers against one real campaign bundle: target-site selection, one finalist structure comparison or measurement, one candidate alignment or annotation review, save-and-restore, and one validated export from each viewer. Run this pass in a fresh Codex task because mounted-viewer session identity is conversation-scoped.

## Structure review packet

For the target and each promoted finalist, preserve:

- campaign and candidate ID;
- target and binder chain IDs;
- author numbering to campaign numbering map;
- site/hotspot residues and their evidence source;
- coordinate-file hash and predictor/model identity;
- prediction seed or ensemble membership;
- interface metrics with their exact source;
- missing measurements as null, not zero;
- failure or exclusion reason.

For every candidate in the locked structure scope, the first report panel shows the binder on the complete target with the requested site highlighted and labeled on a white background. Give the binder a distinct, stable color and keep target, binder, and site colors stable across candidates. Put site-aware metrics beside the panel and link the matching coordinates. Add a site-facing close-up and a contacted/missed/off-site contact panel when those views clarify the result. Inspect interface placement, hotspot recovery, obvious clashes, termini, unsupported loops, and confidence or uncertainty in context. If a render or viewer session is exported, keep it linked to the coordinate hash; never let a screenshot become the only retained evidence.

## Sequence review packet

For target, controls, and candidates, preserve:

- stable record and candidate IDs;
- raw and aligned sequences;
- chain/entity role;
- designed, fixed, forbidden, or hotspot-contact annotations;
- generator/designer and round lineage;
- sequence hash;
- diversity cluster or nearest-neighbor context when computed;
- developability flags and their method source.

Use sequence views to catch truncation, duplicate candidates, native/WT rows accidentally retained from inverse-folding output, violated constraints, and diversity collapse. A motif match is an observation requiring interpretation, not by itself a safety, specificity, or function claim.

## Presentation renderers

The Structure Viewer is the default interactive and reproducible rendering surface inside Codex. Use its typed scene contract, named scenes, PNG output, MP4 timeline, and render sidecars when they satisfy the requested view. The standard scene keeps the whole target visible, gives the binder a distinct color, highlights the locked site, uses a white background, and preserves the same camera convention across candidates.

PyMOL and ChimeraX may add high-polish stills, sessions, or camera-controlled comparisons from the same retained coordinates. Treat each as a separate optional adapter:

- bind every input to a campaign artifact hash and stable candidate ID;
- use an existing adapter or author and retain a narrow reviewed scene script;
- record the exact renderer name and version, chain and residue selections, colors, representations, camera or named view, background, dimensions, and output hash;
- keep the generated scene recipe or command manifest, execution log, image, and receipt together;
- validate image format, dimensions, file integrity, and manifest inclusion before calling the render complete;
- never report PyMOL output as ChimeraX output, or the reverse, and never use visual polish to change a scientific metric or ranking.

If PyMOL or ChimeraX is selected, use the same request and receipt facts as any other companion: exact input hashes, explicit chains and site residues, retained scene source, renderer version, camera, exact invocation, output hashes, and validation. Codex may author that adapter in the campaign workspace. If an external renderer is unavailable, use the Structure Viewer and retain the portable coordinates and renderer-neutral scene intent. The fixed public 1ZVH PyMOL adapter is a technical example, not a restriction on other reviewed adapters.

For a promised HTML delivery, portable coordinates and scene intent are inputs, not finished visuals. The report must show a decodable, browser-inspected binder-on-target image for every candidate in the locked structure scope, highlight the requested site, show site-aware metrics beside the image, and link the corresponding raw coordinates. When video is requested, use the same hash-bound scene for a coherent target overview, site focus, and binder/interface view. A storyboard remains a plan until a decoder-validated MP4/WebM exists, is embedded in the report, and passes browser playback inspection. Apply the [delivery closeout contract](delivery-closeout.md) before calling presentation complete.

## Optional enrichment families

Motif workbenches may provide a richer portable sequence workspace. BioSymphony Structure Factory may provide retained campaign rounds, structure reports, renders, and adapter receipts. Treat both as optional capabilities discovered at runtime:

- private installations may be used only when the user deliberately selects them and data-handling permits it;
- public installations or repositories may be suggested as optional resources, never prerequisites;
- their identifiers, versions, exported artifacts, and any deviations must be recorded when selected;
- no Binder Lane plan may contain a machine-specific path as its portable identity;
- absence or incompatibility falls back to the blessed viewers or portable files.

## Claim boundary

Interactive inspection can reveal inconsistencies and support triage, but it does not raise Binder Lane's computational claim ceiling. Tie that ceiling to validated prediction, controls, and independent support, not visual polish.
