# Cultural Screenplay & Visual Adaptation Studio

## Purpose

A web MVP that will eventually take a short screenplay and adapt it to an exact
Indian culture, dialect, region, setting and script, then produce a complete
production pack. The planned pipeline is:

1. Accept a short screenplay
2. Extract scenes, characters and production elements
3. Select an exact culture / dialect / region / setting / script
4. Research cultural evidence
5. Create a cultural adaptation plan
6. Require human approval
7. Generate an adapted screenplay
8. Generate consistent character / costume / scene visual references
9. Verify continuity
10. Export a production pack

## Current scope

**Phase 0 (foundation)** - Pydantic placeholder models (`Project`, `Scene`, `Character`,
`Costume`, `ProductionElement`), env-based config (`APP_NAME`, `DEBUG`, no API key), and a
Streamlit project form.

**Phase 1 (screenplay ingestion)** - get a screenplay into clean raw text and let the user
inspect it *before* any later processing:

- Input via file upload (`.txt`, `.docx`, `.pdf`) or pasted text
- Text extraction and light normalization into a `ScreenplayDocument`
- A preview of the extracted text with counts and extraction status
- A "Validate Screenplay" step that reports errors and warnings

**Phase 2 (AI-assisted structured extraction)** - converts Phase 1 `raw_text` to a
separate validated structure containing scenes, characters, locations, production elements,
and continuity observations. The bundled development UI currently offers an offline mock
provider. No provider API keys or network access are needed.

**Phase 3 (canonical memory and project state)** - converts Phase 2 extraction into a
validated canonical `ProjectState`, then saves and reloads it as readable JSON under
`data/projects/<project_id>/project.json`. Entity IDs use deterministic prefixes and scene
references are retained. Exact case/whitespace-normalized duplicates may be consolidated;
partial-name matches are candidates only, stay separate, and generate a warning. An explicit
confirmed registry merge preserves aliases, scene references, and non-empty metadata. The
store validates on load and increments the version only when saved content changes. The UI's
**3. Project Memory** section uses `ProjectStore` for persistence.

**Phase 4 (cultural research)** - an evidence-first, local JSON knowledge layer for exact culture/region contexts. It stores source metadata separately from claims, preserves provenance, distinguishes verified / partially supported / insufficient evidence, and labels broad evidence as Rajasthan-general. Retrieval is deterministic and works offline. The current curated starter pack is Marwari / Marwar-Jodhpur, with development defaults for Rural setting and Devanagari script; these are environment-configurable (`RESEARCH_CULTURE`, `RESEARCH_DIALECT`, `RESEARCH_REGION`, `RESEARCH_SETTING`, `RESEARCH_SCRIPT`). It does not generate Marwari dialogue.

**Phase 5 (cultural adaptation planner)** - converts Phase 3 canonical project memory and Phase 4 evidence into a separate, structured, human-reviewable plan. Every evidence reference is checked against the loaded catalog; missing support becomes an explicit review item with no citation IDs. The deterministic mock planner preserves original dialogue and story logic, uses canonical IDs, and never rewrites screenplay content. Human decisions are represented in the plan model and UI.

**Project status: Phases 0–9 completed.** Real cinematic image generation and computer-vision verification, live research provider integration, vector retrieval, OCR and database logic remain outside the implemented scope.
The MockLLMProvider sends nothing to any AI service or over the network. No real provider is
configured in this phase.

## Phase 2 details

The extraction pipeline lives in `app/services/extractor.py` and accepts a
`ScreenplayDocument` plus an `LLMProvider`. Provider implementations return structured data;
the service validates it with Pydantic, normalizes stable IDs and rejects broken references.
`MockLLMProvider` is deterministic and offline. It parses standard INT./EXT. headings,
uppercase dialogue cues, and explicit location/object mentions using a small lexical rule set.
For the documented smoke screenplay it also captures the explicit reference to a letter in
dialogue as a prop, in addition to the old envelope and old table. This is a reasoned extra
element, not an inferred fact. It does not claim comprehensive entity extraction. IDs returned
by the extraction service use stable scene/character/location/prop prefixes. The
`ScreenplayExtraction` models are in `app/models/extraction.py`.

Models cover `Scene`, `Character`, `Location`, `ProductionElement`, `ContinuityState`, and
`ScreenplayExtraction`. Missing facts use `null` or empty collections. The extraction prompt
forbids unsupported invention and cultural adaptation. Warnings and confidence remain visible;
they should not be read as proof that an extraction is complete. Original `raw_text` is retained
unchanged and the structured result is stored separately.

To use the extraction UI, enter or upload text in **1. Screenplay Input**, then use
**2. AI Screenplay Extraction** and click **Extract Screenplay Structure**. The UI shows counts,
warnings, expandable entity sections, and the complete JSON representation.

## Phase 3 details

`ProjectState` reuses the Phase 2 Pydantic scene, character, location, production-element,
and continuity models. `build_project_state()` assigns stable sequential IDs and remaps entity
and scene references. Names are compared after trimming surrounding punctuation and normalizing
case/whitespace. Exact normalized duplicates may merge; partial-name matches are reported as
candidates and kept separate until a caller explicitly confirms a merge in `CanonicalRegistry`.
Confirmed merges retain aliases, scene references, non-empty metadata, and warnings for
conflicting values.

`ProjectStore` writes readable, sorted JSON atomically to
`data/projects/<project_id>/project.json`. Loading always validates with Pydantic. Invalid files
raise `ProjectStateLoadError` and are never overwritten implicitly. Saves preserve canonical
IDs, keep the version and timestamp for unchanged content, and increment the version/update the
ISO 8601 timestamp when content changes. The UI creates project state from the Phase 2 result;
it does not ask users to re-enter entities. Phase 3 stores observations only and adds no cultural
facts or continuity analysis.

The mock extraction and normalizer use deterministic, explicit matching rules. They may leave
ambiguous names separate and cannot resolve screenplay-specific aliases without evidence or a
human-confirmed registry merge. JSON persistence is local to the project workspace and has no
multi-user locking or database migrations.

## Phase 1 details

### Supported input formats

| Format | Library | Notes |
|---|---|---|
| `.txt` | stdlib | UTF-8 (with/without BOM) and UTF-16-with-BOM; falls back to Windows-1252 with a warning |
| `.docx` | python-docx | Paragraphs in order; tables and images are ignored (with a warning) |
| `.pdf` | pypdf | Text layer only, page by page |
| pasted text | - | Taken as-is (after normalization) |

Legacy `.doc`, `.rtf`, `.odt` and everything else are rejected with a clear message.

### Extraction behavior

- Line breaks and indentation are preserved; the screenplay is not rewritten.
- Normalization only: line endings become `\n`, BOM / zero-width space / soft hyphen / control
  characters are removed, non-breaking spaces become spaces, trailing spaces are trimmed, and
  runs of more than two blank lines are collapsed. Zero-width joiners (U+200C/U+200D) are
  kept because Devanagari and other Indic scripts depend on them.
- PDF text is prefixed with a marker per page (`----- Page N -----`) so page boundaries stay
  visible. Word/character counts exclude these markers; `strip_page_markers()` removes them.
- Pages with no extractable text produce a warning naming the page.
- Any extraction problem (corrupt DOCX, invalid or password-protected PDF, binary file named
  `.txt`, unexpected exceptions) never crashes the app: the result has
  `extraction_status="failed"` and the message in `extraction_warnings`.
- `extraction_status` is `success` (no notes), `warning` (extracted, with notes) or `failed`.

### Validation behavior

Errors (screenplay not valid): failed extraction; empty text; fewer than 5 words.
Warnings (still valid): fewer than 50 words; extraction notes such as empty PDF pages or
ignored tables/images; very little text per PDF page (likely scanned); replacement
characters (bad decoding). Short development screenplays are accepted.

### Using the extracted text in later phases

```python
from app.services.ingestion import extract_text
document = extract_text(uploaded_bytes, "script.pdf")   # or extract_text("pasted text")
document.raw_text                                        # input for Phase 2
```

### Known limitations

- No OCR: scanned / image-only PDFs yield no text (a warning is shown).
- PDF text order and line breaks depend on how the PDF was produced; multi-column layouts,
  headers/footers and page numbers are not cleaned up.
- DOCX tables, headers/footers, text boxes and images are not extracted.
- Password-protected PDFs are rejected; AES-encrypted PDFs may additionally need the
  `cryptography` package, which is not installed.
- Legacy Windows-1252 fallback cannot recover text saved in old Indic legacy-font encodings.
- Uploads are limited only by Streamlit's default upload size limit.

## Tech stack

Python 3.11+, Streamlit, Pydantic v2, python-dotenv, python-docx, pypdf, pytest.

## Project structure

```
cultural-screenplay-studio/
├── app/
│   ├── main.py                  # Streamlit entry point
│   ├── config.py                # Env-based settings
│   ├── models/                  # Pydantic models (incl. screenplay.py)
│   ├── models/
│   │   └── adaptation.py        # Phase 5 plan and review models
│   ├── services/
│   │   ├── ingestion.py         # TXT/DOCX/PDF/pasted-text extraction
│   │   ├── cultural_store.py    # Phase 4 evidence JSON storage
│   │   ├── cultural_retriever.py # Phase 4 structured retrieval
│   │   ├── adaptation_planner.py # Phase 5 deterministic planner
│   │   ├── adaptation_store.py   # Phase 5.1 versioned plan persistence
│   │   └── validators.py        # File-type and screenplay validation
│   └── ui/
│       ├── screenplay_input.py  # Phase 1 and 2 sections
│       ├── project_memory.py    # Phase 3 Project Memory section
│       ├── cultural_research.py # Phase 4 research section
│       └── adaptation_plan.py   # Phase 5 review section
├── data/
│   ├── projects/                # future project storage
│   └── culture/                 # future cultural data
├── tests/
│   ├── test_adaptation_planner.py # Phase 5 planner, evidence and review tests
│   ├── test_cultural_research.py # Phase 4 evidence/retrieval tests
│   ├── test_foundation.py       # Phase 0
│   ├── test_ingestion.py        # Phase 1
│   ├── test_validators.py       # Phase 1
│   └── factories.py             # builds tiny DOCX/PDF files for tests
├── .env.example
├── requirements.txt
└── run.py                       # convenience launcher
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # optional
```

## Run the app

```bash
streamlit run app/main.py
# or
python run.py
```

Then open http://localhost:8501.

## Run the tests

```bash
pytest            # all phases
pytest tests/test_ingestion.py tests/test_validators.py   # Phase 1 only
pytest tests/test_extraction.py                            # Phase 2
```


## Phase 4 details: cultural research and evidence

Phase 4 provides an evidence layer only. It does not modify screenplay text or Phase 3 project memory. The UI's **4. Cultural Research** section shows the selected culture, dialect, region, rural/urban setting and script. Its current **Research Cultural Context** action loads a reviewed local pack through the `CulturalResearchProvider` interface; it does not call a search engine or fail when offline.

### Evidence-first design

Every cultural claim is a `CulturalEvidence` record linked by `source_id` to a separate `CulturalSource` record. Evidence also keeps a source title/URL/type snapshot so cards remain traceable; later decisions can cite the stable `evidence_id`. Evidence categories are free-form strings so the store does not force claims into unsupported categories. Language phrases use `LanguageEvidence` with phrase, meaning, context, source, confidence and regional scope. No phrase is seeded for Marwari because the starter sources do not provide phrase-level dialect evidence.

Source priority is a simple retrieval ordering: government and institutional sources first, then museums, academic research, reputable references, and other sources. A priority tier does not itself prove a claim. Each source has reliability notes describing its limits. The initial records use Rajasthan Foundation and Rajasthan Tourism pages and summarize only the claims those pages support.

### Cultural scope and status

A Marwar/Jodhpur-specific statement is labeled at that scope. A statewide Rajasthan statement remains `culture="Rajasthan"`, `scope="Rajasthan-general"`, even when shown alongside a Marwari query. It is accompanied by a warning and is never silently narrowed to Marwari. Rural architecture, everyday behavior, greetings and other areas without adequate source support remain unknown.

Evidence status values:

- `verified`: the source directly supports the stated bounded claim.
- `partially_supported`: the source supports some or event-specific aspects, but not a broad/generalized claim.
- `insufficient_evidence`: current evidence cannot support a usable factual claim; language evidence can preserve an explicit unknown.

Model inference is not evidence. A no-match result includes an unknown warning. If records share a `conflict_group` but make different claims, the store preserves both and reports a **Cultural evidence conflict** listing evidence IDs, source titles and claims; it does not select a winner.

### Retrieval and adding sources

`CulturalStore` provides `add_source`, `add_evidence`, `get_source`, `get_evidence`, `list_evidence`, `search_evidence`, `save` and `load`. It stores JSON under `data/culture/<culture_region>/`, validates Pydantic models and source references, and writes files atomically. Duplicate IDs with changed content are rejected; duplicate evidence from the same source is ignored with a warning. `CulturalRetriever` exposes deterministic keyword matching plus category, culture, region, source type, minimum confidence and status filters; its structured result interface can later be extended with semantic retrieval.

To add a reviewed source, construct a `CulturalSource` with its real URL, publisher, source type, retrieval timestamp and specific reliability notes, then call `store.add_source(source)`. Add each concise and bounded claim separately with a unique `evidence_id`, its `source_id`, evidence summary, scope, confidence and status. Set `scope="Rajasthan-general"` for statewide sources; use a Marwar/Jodhpur scope only when the source supports it. Save with `store.save()`. Search through `store.search_evidence(culture="Marwari", region="Marwar / Jodhpur", category="clothing", query="bandhej")`; the result contains structured `matched_evidence`, `total_matches` and warnings.

The initial pack includes 7 government-published sources, 12 evidence records and one insufficient phrase-level language record. It covers regional context, language, clothing, textiles, architecture, landscape, music, dance, rituals and food; categories without reliable support are shown as unknown. Since the UI uses a curated local provider, new live web research must be reviewed and ingested separately.


## Phase 5 details: cultural adaptation planning

**The adaptation plan is generated before screenplay rewriting and requires human review.** Phase 5 consumes the Phase 3 `ProjectState`, the matching Phase 2 `ScreenplayExtraction`, Phase 4 `CulturalEvidence` records and (when available) the original screenplay text. It creates a separate `AdaptationPlan` with the project's selected culture, dialect, region, setting and script. It never mutates screenplay text, extraction, project memory, scene order, story events or character relationships.

`create_adaptation_plan()` is deterministic in its planning rules and can be called without Streamlit. `MockAdaptationPlanner` supplies stable IDs and timestamps for repeatable offline checks. The planner creates review items only for relevant screenplay elements: recurring character identity, speaker dialogue, scene-specific clothing, and scene cues that overlap with available evidence. It does not fill every adaptation category. A plan and each change begin unapproved; change states include pending, needs review, needs revision, approved and rejected, with `insufficient_evidence` for unsupported items. The UI limits approval decisions for items that have no evidence.

Each change points to canonical `SCENE_...`, `CHAR_...` or production element IDs. Evidence IDs are validated against the supplied catalog and must resolve to existing Phase 4 records. Evidence-backed proposals remain conditional review leads, and the plan displays each cited claim, source, scope, confidence and URL. Rajasthan-general evidence remains marked as such and adds the warning **"Evidence is Rajasthan-general rather than Marwar-specific."** The planner does not convert statewide customs or food into Marwar facts.

The Phase 4 pack has no source-verified Marwari phrase/meaning/context records. Therefore the planner preserves each located original dialogue excerpt verbatim, emits no replacement Marwari text and marks dialect items `insufficient_evidence` with the warning **"Phrase-level Marwari evidence is not currently available in the cultural evidence pack."** If original text is unavailable, it says so rather than fabricating a quote. Unsupported costume, character-social-context and other scene-relevant choices are likewise explicit review items with empty `evidence_ids` and the warning **"Insufficient evidence for a culture-specific adaptation."**

The **5. Cultural Adaptation Plan** panel summarizes proposed, evidence-backed, review-required and insufficient-evidence changes; it filters by scene, category, status and confidence. Expand a change to inspect evidence traceability. The machine-readable `AdaptationPlan` JSON is available in the same panel. Phase 5.1 persists the plan and review status in `data/projects/<project_id>/adaptation_plan.json`.


The planner also preserves competing source claims. Conflicting evidence is attached as separate IDs where relevant, flagged as **Cultural evidence conflict**, and left in `needs_review`; the planner does not silently select a claim. Human review decisions are persisted by Phase 5.1 through `AdaptationStore` after an explicit save action.


## Phase 5.1 details: adaptation plan persistence

`AdaptationStore` stores one `adaptation_plan.json` at `data/projects/<project_id>/adaptation_plan.json`. It is independent of Streamlit, validates JSON with the `AdaptationPlan` Pydantic model, writes atomically and rejects unsafe project IDs. `save_plan()` creates the first saved plan and will not overwrite an existing plan. `load_plan()` restores it after a session/application restart. `update_plan()` accepts plan/change review status changes only; it rejects changed change IDs, order, evidence references or proposal content.

Plans include `version` (starting at 1). A persisted review change increments the version and refreshes `updated_at`; a no-op save leaves both unchanged. `created_at`, stable `change_id` values and evidence IDs are preserved. The Phase 5.1 UI provides **Save Adaptation Plan**, per-change review controls, **Save Review Decisions**, and **Load Saved Plan**. If Phase 3 state is not loaded after restart, a saved plan can still be loaded by project ID; load Phase 3 state to generate a new plan. Approval only persists the review decision and never triggers screenplay rewriting.

## Phase 6 details: approval-gated screenplay adaptation

Phase 6 creates a separate `AdaptedScreenplay` artifact. **Only human-approved adaptation changes are eligible for screenplay rewriting.** The Phase 5 plan is loaded from persistent project storage before adaptation, and pending, rejected, needs-revision, or insufficient-evidence items are not applied. Approval records human intent; it does not edit the source screenplay or project memory.

`ScreenplayAdapter` is a provider interface with an offline deterministic `MockScreenplayAdapter`. The mock inserts explicit, traceable annotations for eligible changes; it does not pretend to produce polished dialogue or culturally authored prose. Adaptations are blocked when their evidence is missing, incompatible with the claim's category/culture/region, or only Rajasthan-general when a Marwar-specific assertion is requested. Marwari dialogue is also blocked while the evidence pack lacks reliable phrase-level dialect material. The original screenplay text is retained verbatim in the adapted artifact.

`AdaptationValidationResult` checks project and screenplay identity, scene count and ordering, original text preservation, approval status, change IDs and evidence traceability. The output is stored separately at `data/projects/<project_id>/adapted_screenplay.json`; it does not overwrite `project.json`, the Phase 1 screenplay, or the Phase 5 plan. The **6. Adapted Screenplay** panel loads the saved Phase 5 plan, generates an adapted artifact, shows original and adapted text per scene, reports applied/blocked changes and citations, validates it, and offers explicit save/load controls.

To use Phase 6, load project state and the original Phase 1 screenplay, generate and save a Phase 5 plan, then persist human review decisions in Phase 5.1. In Phase 6, load the persisted plan and generate the adapted output. The evidence IDs remain attached to each applied change so later review can trace a choice back to its cultural source. Unsupported choices remain unchanged and carry blocking reasons instead of being filled in from model assumptions.

## Phase 7 details: visual production pack specification

Phase 7 creates a structured `VisualProductionPack` for future production tooling. It does not generate images or call an image service. The pack contains one `CharacterVisualBible` for every canonical Phase 3 character, costume variants only when an approved supported change justifies one, and exactly one ordered `SceneVisualKeyframe` for each canonical scene. The generator uses the Phase 6 adapted screenplay and the persisted Phase 5 plan; inputs from earlier phases are treated as read-only.

`MockVisualPackGenerator` is deterministic and offline. Unspecified age, face, body, hair, grooming, clothing, architecture, lighting and camera details remain empty or `unspecified`; no Marwari or regional detail is inferred. Cultural details are included only when the change is human-approved, appears in the Phase 6 adapted artifact, and its evidence IDs resolve to category-compatible records. An unavailable or insufficient reference blocks that specific claim and adds a warning. Rajasthan-general evidence is labeled as general and is never narrowed to Marwar/Jodhpur.

`validate_visual_pack()` checks canonical character/scene/prop references, exactly-one-keyframe coverage and order, character and costume consistency, approved-change linkage, evidence IDs and evidence scope. `VisualValidationResult` reports errors, warnings, missing references, unsupported cultural details and counts. Shared character bibles provide a single appearance source across scenes; missing identity traits stay unknown to prevent random changes. Costume variants have separate stable IDs and scene references, so an intentional costume change does not become a character identity conflict.

`VisualPackStore` atomically stores the validated Pydantic model at `data/projects/<project_id>/visual_production_pack.json`, separately from `project.json`, `adaptation_plan.json` and `adapted_screenplay.json`. It validates data on load, rejects unsafe project IDs and increments pack version on replacement while preserving creation time and stable IDs. The **7. Visual Production Pack** panel can generate, validate, save and load the spec, and shows character bibles, costume bibles, scene prompts, evidence IDs and warnings.

The provider-ready prompt is a labeled specification for subject, characters, appearance, costume, place, architecture, environment, props, lighting, framing, composition, mood and supported cultural details. Its evidence IDs and change IDs remain in structured fields for provenance; a future image provider can build a provider-specific prompt from this validated pack. Do not treat a prompt as evidence or as proof that an image was generated.

Run the complete offline suite with `pytest -q` (or `python -m pytest -q` in the configured environment). Phase 7 tests are in `tests/test_visual_pack.py`, `tests/test_visual_continuity.py` and `tests/test_visual_pack_store.py`.

## Phase 8 details: approval-gated visual generation orchestration

Phase 8 consumes the saved Phase 7 `VisualProductionPack` and creates a `VisualGenerationBatch` of stable `VisualGenerationRequest` records for every valid canonical character, supported costume variant and ordered scene keyframe. Scene request prompts reuse the Phase 7 `generation_prompt` and `negative_prompt` verbatim. Each request carries its source entity, scene, evidence IDs, visual-spec version, provider name and deterministic prompt hash. Invalid packs or invalid individual entity references are skipped with structured warnings.

`ImageGenerationProvider` is a provider boundary selected through `get_image_generation_provider()`. The default `MockImageGenerationProvider` writes a deterministic SVG label card that explicitly says **MOCK PLACEHOLDER — NOT A REAL GENERATED IMAGE**. It does not call a model, download imagery, or claim visual similarity. A future provider can be registered behind the same interface without changing the planner or approval flow.

Requests begin as `pending`. The UI persists each human decision immediately; only `approved` requests can reach the provider. `reconcile_generation_batch()` keeps approvals for unchanged prompts and moves changed prompts to `needs_review`, removing stale artifacts from the active batch. The generation service recomputes prompt hashes immediately before use, catches per-request provider/storage failures as `failed` artifact records, validates successful artifact metadata and is idempotent for already-generated requests. Pending, rejected and needs-review requests are never sent.

`VisualArtifactStore` stores media under `data/projects/<project_id>/visuals/` and request, decision, batch and artifact metadata in `data/projects/<project_id>/visual_artifacts.json`. Writes are atomic; IDs and evidence links are retained, project IDs are path-validated, and prior project, adaptation and visual-pack files are separate. `validate_generated_visuals()` compares artifact identity, request/prompt/spec hashes, canonical character/costume/scene references, evidence metadata and scene order with the current Phase 7 specification. Mock validation is metadata/specification validation only; it is not computer vision or a cultural-authenticity check.

The **8. Visual Generation** panel creates requests without generating them, shows request prompts and statuses, persists Approve / Reject / Needs Review decisions, generates only approved requests, validates outputs, saves/loads artifacts and displays labeled mock placeholders. The app does not auto-run all requests after planning.

**Phase 8 supports provider-based visual generation orchestration and deterministic mock artifacts. The default development provider does not produce real cinematic images. Real image generation and computer-vision-based visual similarity checks require a configured provider/integration.**

Run all deterministic tests with `pytest -q`. Phase 8 coverage is in `tests/test_visual_generation.py`, `tests/test_image_generation_provider.py`, `tests/test_generated_visual_validator.py` and `tests/test_visual_artifact_store.py`.

## Phase 9 details: final validation and production export

Phase 9 combines saved Phase 3–8 artifacts into a referenced `ProductionPackage`, a
structural `ContinuityReport`, an AI usage log and an explicit limitations report. It checks
scene IDs/order, approved adaptation references, source-screenplay preservation, evidence to
source URLs, visual bibles/keyframes, approved visual requests, artifact links and prompt
hashes. A successful validation means structural consistency and traceability only; it does
not establish cultural authenticity or visual similarity. Warnings and unresolved items are
carried into the report and limitations export.

The **9. Final Production Package** panel loads persisted artifacts, runs final validation,
builds a package summary, and requires a separate **Export Production Package** action. A
structural error blocks export. Missing or unresolved cultural support remains visible. The
Phase 1 screenplay document is session-scoped in the current app; when it is unavailable, the
panel uses the original-text snapshot retained by the persisted adapted screenplay and labels
that provenance accordingly.

Exports are stored under `data/projects/<project_id>/exports/<package_id>/` and contain the
adapted screenplay JSON/text, project breakdown, cited cultural evidence with source metadata,
character/costume bibles, scene keyframes, visual artifact metadata/media, continuity report,
AI usage log, limitations and `12_manifest.json`. The manifest records SHA-256 checksums and
sizes for every payload file except itself (a manifest cannot contain its own checksum). The
optional ZIP mirrors the exact export directory tree and does not bundle unrelated project
files, credentials, virtual environments, Git internals or caches. `load_manifest()` verifies
the exported files against their recorded hashes.

AI usage entries distinguish deterministic/offline processing, mock providers, and steps not
run; no external LLM or image-generation call is claimed unless a future provider records it.
Known limitations include phrase-level Marwari evidence gaps, locally curated rather than
exhaustive research, mock visual placeholders, and the absence of computer-vision similarity
checks. Use `validate_final_project()` and `export_package()` for non-UI integration; both are
independent of Streamlit. Phase 9 tests are in `tests/test_final_validator.py`,
`tests/test_production_export.py`, `tests/test_ai_usage.py`, `tests/test_manifest.py`, and
`tests/test_final_package.py`.
