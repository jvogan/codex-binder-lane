# Delivery closeout contract

Use this contract when a Binder Lane campaign promises an HTML report, visible candidate sequences, structure visuals, or video. Computational execution and presentation delivery are separate gates.

## Lock the presentation before execution

In `evidence.presentation`, lock the HTML report, visible sequences, structure visuals, and video. A normal generated-binder campaign starts with the report, sequences, and structure visuals set to `required`; video remains `not-requested` unless the user asks for it. Also lock the candidate scope:

- `sequence_scope: all-generated` means every generated candidate sequence appears in the delivery, not only the lead;
- `structure_scope: all-predicted` means every predicted candidate has its raw coordinates and at least one decodable, browser-inspected render in the delivery;
- `browser_verification: required` is mandatory whenever an HTML report is promised.

Do not silently shrink these scopes during closeout. If a requested artifact cannot be produced, report presentation delivery as incomplete and name the missing item. A correct computational stop condition does not waive a requested delivery.

The delivery index must copy its target, chain, numbering, and site residues from the frozen target/site lock. Retain the plan, lock, packet, and result-package hashes beside the operator record. A future campaign-level closeout will compare the whole multi-stage graph automatically; until then, do not describe the presentation check as proof that every planned computation ran.

## Keep two manifests

An archive manifest may cover logs, caches, downloaded repositories, provider workspaces, and other retained execution material. It is not the user-facing delivery inventory.

Create a separate `delivery-index.json` from [`delivery-index.template.json`](../assets/delivery-index.template.json), using schema `codex-binder-delivery-index/v2`. Its `delivery_files` list is the exact curated file set for the delivery root: the target and site lock, reports, candidate FASTA files, target–binder coordinates, site-aware metric tables, render recipes, decodable images, requested video, viewer exports, browser evidence, receipts, and cost/cleanup closeout. The validator rejects undeclared files, symlinks, and special files anywhere in that tree. Do not include `node_modules`, virtual environments, vendored source trees, example repositories, or tool caches.

Every artifact reference contains its relative path, lowercase SHA-256, and exact byte count. Every candidate record contains its stable ID and the structures within the locked scope. Unless `sequence_visibility` is `not-requested`, it also contains one single-record FASTA whose record ID matches the candidate ID. Each structure record contains its route, a stable `render_id`, raw PDB/mmCIF target–binder coordinates, a metric file, at least one site-aware metric, a render recipe, and a decodable image.

For each structure in scope, `visual_context` must name the target chains, binder chains, exact locked site residues, renderer, renderer version, and render recipe. It must declare `view_kind: binder-on-target-site`, `target_visible: true`, `binder_visible: true`, `site_highlighted: true`, and `background: white`. The render recipe ties the coordinate and image files together through their recorded hashes while allowing useful extra camera, color, and representation settings. These fields make the intended scientific view explicit; they do not replace inspection of the rendered pixels.

## Make the HTML self-evidencing

The report must retain accessible static evidence even when a JavaScript application adds richer interaction. Use these semantic markers:

```text
code element: data-binder-sequence="CAND-001" with ACDEFG... as its text
link element: data-sequence-download="CAND-001" and href="../sequences/CAND-001.fasta"
image element: data-structure-render="cand-001-fast", data-target-chains="T", data-binder-chains="B", data-target-site="T:10,T:12", data-site-highlighted="true", data-background="white", and src="media/cand-001-fast.png"
caption element: data-structure-caption="cand-001-fast" and visible text such as "CAND-001 binder on TARGET-1 at locked site T:10 and T:12"
link element: data-structure-download="cand-001-fast" and href="../structures/cand-001-fast.cif"
element containing visible metrics: data-site-metrics="cand-001-fast"
video element: data-campaign-video, data-video-scenes="cand-001-fast-site", controls, and src="media/campaign.mp4"
```

The full sequence must be visible, not only present in a download. Each rendered structure needs a visible caption naming the candidate, target, and every locked site residue. The first structure panel for each candidate must show the complete target, the binder in a distinct visual style, and the exact requested site highlighted and labeled on a white background. Put the site's measured metrics beside the image and link the matching coordinates. A coordinate file is not a structure visual. A scene recipe or storyboard is not a rendered image or video. Candidate IDs and route labels must stay consistent across the report, filenames, metrics, and viewer exports.

## Verify the rendered report

Open the final HTML in a browser and check the overview, requested sequence sections, and structures. Retain one non-tiny browser capture for every reported candidate/render pair. Each `report.browser_verification.captures` entry contains `candidate_id`, `render_id`, and a `screenshot` artifact with its recorded hash. When video is delivered, also check playback and retain the `video-playback` check.

A delivered video needs browser playback controls and a strict JSON storyboard with schema `codex-binder-video-storyboard/v1`. The storyboard records the video hash and lists scenes with `scene_id`, `candidate_id`, `render_id`, `render_sha256`, `start_seconds`, and `end_seconds`. Every scene must refer to a delivered target–binder render; the HTML video lists the same scene IDs in `data-video-scenes`. This permits a focused video of selected candidates without pretending it covers every candidate.

The validator decodes PNG pixels, rejects active or externally loading SVG content, requires a local `ffmpeg` frame decode for JPEG/WebP, and requires local `ffprobe` metadata plus a full local `ffmpeg` video decode for MP4/WebM. Install both commands before validating deliveries that contain those media formats. These checks establish a decodable delivery artifact, not scientific correctness or an independent proof that the render depicts the coordinates.

Record Molecular Structure Viewer and Biological Sequence & Alignment Viewer states independently: packet, runtime, invocation, output validation, and output references. When a mounted viewer is callable, exercise it and retain a validated export or saved session. If it is unavailable, keep the portable files and state the fallback plainly; never convert `packet: emitted` into an implied interactive review.

## Run the closeout gate

From the installed skill directory:

```bash
cp "$SKILL_DIR/assets/delivery-index.template.json" \
  CAMPAIGN_DELIVERY_ROOT/delivery-index.json
python3 "$SKILL_DIR/scripts/validate_delivery.py" CAMPAIGN_DELIVERY_ROOT \
  --index delivery-index.json --json
```

Only a passing result permits `presentation delivery: passed`. If computation reached its declared stop condition but this validator fails, say:

> Computational campaign stopped at the declared gate; presentation delivery is incomplete.

Do not use an unqualified `completed`, `done`, or `release ready` until both the computational closeout and the presentation closeout have passed.
