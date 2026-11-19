# Slide Pipeline Project Plan

Last updated: 2026-07-17

## Goal

Build a repeatable service that accepts any valid v1 reusable learning object
(RLO), selects suitable presentation archetypes, fits grounded content into
their declared capacities, validates the result deterministically, and renders
an interactive browser-ready course.

The committed ADKAR and Kotter RLOs are regression examples, not product
requirements. No pipeline behavior may depend on their IDs, titles, topic
vocabulary, component ordering, or known `canonical_content` shapes.

## Non-Negotiable Architecture Rules

### OpenAI-Compatible Model Access Through LiteLLM

- All text generation, structured output, embedding, and image-generation
  requests go through the LiteLLM proxy.
- Application code uses OpenAI-compatible clients. Do not add direct provider
  SDKs or call provider-specific endpoints from the pipeline.
- PydanticAI agents use `OpenAIChatModel` with `OpenAIProvider`, configured with
  `LITE_LLM_BASE_URL`, `LITE_LLM_API_KEY`, and a purpose-specific alias declared
  in `litellm/config.yaml`.
- Existing non-agent calls use the OpenAI Python client with the same LiteLLM
  base URL and key, loaded through the shared `llm_gateway` configuration
  module so defaults and error handling cannot drift.
- Model names in application code are LiteLLM aliases such as
  `slide-content-fitting`, `component-catalog-embedding`, and
  `slide-image-generation`; upstream
  provider model names remain in `litellm/config.yaml`.
- Tests must not require a live model provider unless explicitly marked as an
  opt-in integration test.

Current model-access audit:

- [x] Legacy slide text generation uses the OpenAI Python client pointed at
  LiteLLM (`pipeline/src/llm.py`); it will be replaced by the PydanticAI
  OpenAI-compatible adapter in Phase 3.
- [x] Component embeddings use the OpenAI Python client pointed at LiteLLM.
- [x] API RLO embeddings use the OpenAI Python client pointed at LiteLLM.
- [x] Image generation uses the OpenAI Python client pointed at LiteLLM.
- [x] Podcast TTS uses the OpenAI Python client pointed at LiteLLM.
- [x] The Google client in the API is used only for GCS object storage, not
  model access.
- [x] Centralize the duplicated OpenAI-compatible client configuration.
- [ ] Add a test that fails if a new model-provider SDK is imported by the
  pipeline or API model-access modules.

### Content-Agnostic Operation

- Accept any document that validates as `rlo_schema.RLO`, not only committed
  examples.
- Select layouts from pedagogical and structural signals: content type, CDT
  type, misconception presence, assessment type, value shape, and component
  capacity.
- Never branch on an RLO ID, named methodology, title keyword, or fixture file.
- Treat `Component.canonical_content` as genuinely open-shaped data: string,
  list, scalar, or nested object. Prompts and source resolution must serialize
  the supplied value without assuming topic-specific keys.
- Generated claims must remain traceable to valid RLO source references.
- Use synthetic, topic-neutral RLO fixtures for primary tests. Use the 22
  committed RLOs only for schema validation, smoke tests, and regression
  coverage.

### Deterministic Boundaries

- The model may propose layouts and wording; deterministic code validates
  schema, component existence, capacity, source references, sequence rules,
  assessment fidelity, and text budgets.
- Invalid output produces actionable retry feedback or a typed terminal error.
  It must never be silently truncated, accepted, or replaced with invented
  content.
- Rendering does not call an LLM and works from saved normalized course
  content.
- Core service code has no CLI, filesystem-output, Docker, or HTTP assumptions.

### Docker Is the Supported Test Environment

- Every automated test must run in the pipeline or API Docker image.
- Local host Python packages are optional and are not a prerequisite.
- Docker build failures, import failures, and tests are release blockers.
- No implementation phase is complete until its Docker verification commands
  pass.
- Nothing under `manim/` is modified by this work.

## Decisions Required Before Agent Integration

- [x] Define assessment overflow policy. Assessment stems, options, and
  per-option feedback are source-of-truth content and must not be paraphrased
  merely to satisfy a visual budget. Choose an adaptive/paginated template or
  return a typed capacity error.
- [x] Choose and document the production minimum-density ratio used when a slot
  has `target_chars` but no explicit `min_chars`.
- [x] Pin PydanticAI to a supported major/minor range and record the tested
  version in the Docker image. The current broad `>=0.0.14` range is unsafe.
- [x] Decide whether Qdrant ranking adds value for a small component registry.
  Selection correctness must not depend on Qdrant availability or result
  ordering.

## Phase 0 — Shared v1 Schema Package

Status: complete.

- [x] Create the root `rlo_schema/` package.
- [x] Add v1 models and major-version dispatch.
- [x] Switch API schema imports to `rlo_schema`.
- [x] Remove the old API-owned schema package.
- [x] Use repository-root Docker build contexts for API and pipeline images.
- [x] Add a root `.dockerignore`.
- [x] Copy `rlo_schema/` into both Docker images.
- [x] Validate all 22 committed RLO documents against the shared schema.

## Phase 1 — Deterministic Budget Validation

Status: complete. The production derived minimum-density ratio is 0.4.

- [x] Declare text and item capacities in component registry descriptors.
- [x] Implement `Violation`, `validate_budgets()`,
  `format_violations()`, and derived minimum floors.
- [x] Validate scalar text slots.
- [x] Validate arrays and arrays of nested objects.
- [x] Validate arrays of scalar strings described by `item_slots.text`.
- [x] Validate nested object slots such as comparison columns.
- [x] Recurse derived minimum floors through arrays and objects.
- [x] Add deterministic unit tests.
- [x] Pass 10 constraint tests inside the pipeline Docker image.

## Phase 2 — v1 Pipeline Contracts and Generic Grounding

Status: substantially complete; synthetic RLO fixtures remain.

- [x] Remove the legacy `Rlo` input model from `pipeline/src/schema.py` and
  import `rlo_schema.RLO` at pipeline boundaries.
- [x] Keep presentation models separate from the source schema; rename the
  module if needed to make the distinction explicit.
- [x] Update plan metadata to use v1 identity/version fields.
- [x] Implement a strict, reusable RLO source-reference resolver.
- [x] Reject missing, malformed, or out-of-range source references instead of
  resolving them to `None`.
- [x] Support generic traversal of dictionaries, lists, Pydantic models, and
  open-shaped `canonical_content` values.
- [x] Add deterministic validation that every planned screen has resolvable
  source references.
- [ ] Define normalized grounding payloads for title, objective, concepts,
  components, misconceptions, assessments, and completion content.
- [x] Preserve per-option assessment feedback from
  `assessment_items[].options[].feedback`.
- [x] Support or explicitly reject `open_response` assessment items with a
  typed, documented result.
- [ ] Add synthetic RLO fixtures covering string, list, and nested-object
  component content.
- [ ] Add tests proving no source resolver or planner helper contains fixture
  IDs or topic-specific vocabulary.

## Phase 3 — OpenAI-Compatible PydanticAI Agent Layer

Status: implemented; deterministic agent-model tests remain.

- [x] Create one LiteLLM/OpenAI-compatible configuration factory used by all
  pipeline model clients.
- [x] Implement `make_model()` with PydanticAI `OpenAIChatModel` and
  `OpenAIProvider(base_url=..., api_key=...)`.
- [x] Ensure each selected model name is a purpose-specific alias declared in
  `litellm/config.yaml`.
- [ ] Add configuration tests for base URL, API key handling, and model alias
  without making a network call.
- [x] Implement a typed `SelectionAgent` result.
- [x] Give the selection agent the complete eligible registry inventory, or a
  deterministic capacity-filtered inventory; do not depend on a truncated
  Qdrant fallback result.
- [x] Select using descriptor `when_to_use`, structured RLO signals, and slot
  capacity.
- [ ] Deterministically reject unknown archetype IDs and capacity-incompatible
  selections.
- [x] Deterministically validate required course positions and sequence
  invariants.
- [x] Implement a typed `FittingAgent` result for each presentation model.
- [x] Pass only resolved source material into a fitting run.
- [x] Add a PydanticAI output validator that calls `validate_budgets()`.
- [x] Raise `ModelRetry(format_violations(...))` when repair is possible.
- [x] Bound retry attempts and return a typed failure when the content cannot
  fit without violating source fidelity.
- [x] Rewrite `planner.py` around `SelectionAgent`.
- [x] Rewrite `expander.py` around `FittingAgent`.
- [x] Delete `pipeline/src/llm.py` after all callers have migrated.
- [x] Audit embeddings, images, podcasts, and other model calls to confirm they
  all use an OpenAI-compatible client pointed at LiteLLM.
- [ ] Add PydanticAI `FunctionModel` or equivalent deterministic tests for
  valid output, malformed output, budget retry, retry exhaustion, and source
  fidelity.

## Phase 4 — Service Entrypoint and Artifact Contract

Status: implemented; usage aggregation and a fake-agent service test remain.

- [x] Rename the low-level renderer function to avoid colliding with the
  service-level `render_course()` name.
- [x] Add `pipeline/src/service.py`.
- [x] Define `render_course(rlo: RLO, *, theme: str) -> RenderResult`.
- [ ] Define `RenderResult` with normalized course content, screen plan, HTML,
  warnings/failures, and model usage metadata.
- [x] Keep the service free of CLI parsing and mandatory filesystem writes.
- [x] Make image generation optional and injectable.
- [x] Make registry/model dependencies injectable for unit tests and workers.
- [x] Make `generate.py` a thin adapter for file/API input and artifact output.
- [x] Keep `rerender.py` LLM-free and compatible with saved normalized output.
- [x] Add a Docker service test using fake agents and no network.

## Phase 5 — General Template and Interaction Library

Status: complete for the planned archetypes.

Each archetype requires a presentation model, registry descriptor, Jinja2
template, CSS/JavaScript behavior, accessibility behavior, fixture, and
renderer test.

- [x] `process_sequence` — ordered steps, dependencies, or timeline.
- [x] `misconception_buster` — misconception/correction pairs.
- [x] `comparison_table` — arbitrary items by arbitrary dimensions within
  declared capacity.
- [x] `tabbed_content` — grouped details with keyboard-accessible tabs.
- [x] `rule_card` — a definition or principle with supporting detail.
- [x] `reflection_prompt` — ungraded learner reflection/self-check.
- [x] `key_takeaways` — concise recap list.
- [x] Upgrade `knowledge_check` for per-option diagnostic feedback.
- [x] Add a deterministic component gallery that renders every archetype
  without an LLM.
- [x] Verify every interaction with mouse and keyboard.
- [x] Verify templates render arbitrary synthetic labels and content rather
  than framework-specific examples.

## Phase 6 — Deloitte Brand and Theme Composition

Status: implemented; automated theme assertions and contrast checks remain.

- [x] Create `brand/deloitte.yaml` without modifying `manim/`.
- [x] Create Deloitte light/green and dark theme files.
- [x] Define how theme semantic tokens reference canonical brand palette
  tokens instead of duplicating raw colors.
- [x] Merge brand tokens before theme overrides in `load_theme()`.
- [x] Emit resolved CSS variables with deterministic fallback behavior.
- [x] Use Open Sans and the agreed Deloitte type scale.
- [x] Restyle spacing, borders, accents, focus states, and light/dark surfaces.
- [ ] Add renderer tests for token precedence and missing-theme fallback.
- [ ] Add automated contrast checks for core foreground/background pairs.
- [x] Confirm `git diff --name-only -- manim` remains empty.

## Phase 6.5 — Scalable Template Candidate Retrieval

Status: complete for dense filtered retrieval; relevance evaluation should grow
with the template catalog.

- [x] Introduce typed slide categories, density, media requirements, and
  template-independent `SlideNeed` records.
- [x] Split planning into slide-needs planning and shortlisted template selection.
- [x] Add retrieval-focused metadata to every template descriptor.
- [x] Index one Qdrant point per selectable layout variant.
- [x] Store compact retrieval payloads and hydrate full descriptors only after search.
- [x] Use category, item-capacity, and required-media payload filters before ranking.
- [x] Batch need embeddings and use the current Qdrant `query_points()` API.
- [x] Retrieve up to 20 raw matches, diversify by template family, and expose at
  most eight hydrated candidates to the selector.
- [x] Allow fewer than five candidates when hard constraints leave fewer valid choices.
- [x] Refresh changed descriptor vectors using content hashes and remove obsolete records.
- [x] Create payload indexes for fields used by eligibility filters.
- [x] Replace arbitrary first-N fallback with deterministic eligibility and ranking.
- [x] Preserve the selected `layout_variant` through planning and fitting.
- [x] Add a grounded `video_player` media archetype.
- [x] Verify live retrieval for text-heavy concepts, assessment, and required video.
- [x] Run a stored RLO end-to-end using needs → retrieval → selection → fitting.
- [ ] Build a larger retrieval evaluation set with expected, acceptable, and
  forbidden candidates as the registry grows.

## Phase 6.6 — Corporate E-Learning Design Catalog

Status: searchable catalog and first reusable families complete; richer
interaction and diagram families remain an implementation backlog.

The catalog is intentionally broader than the renderer. Qdrant stores both
`ready` variants and `planned` design concepts. Production planning applies an
`implementation_status = ready` filter; design discovery can query both through
`search_catalog()`. A planned concept names its `suggested_family` so multiple
instructional uses can converge on one reusable code contract.

- [x] Define high-level slide categories: intro, content, practice, assessment,
  media, navigation, and completion.
- [x] Describe 57 planned design concepts using instructional purpose, content
  shape, relationship, interaction, density, sequence position, media needs,
  and item capacity—not topic or methodology keywords.
- [x] Cover orientation and relevance patterns: agenda, prerequisites,
  navigation tutorial, module map, and why-this-matters.
- [x] Cover explanatory patterns: cards, image splits, statistics, callouts,
  disclosures, comparisons, checklists, diagrams, matrices, hotspots, and charts.
- [x] Cover application patterns: cases, dialogue, reveals, walkthroughs,
  simulations, matching, sorting, ordering, role play, and decision trees.
- [x] Cover assessment patterns: multiple choice, true/false, matching,
  ordering, fill-blank, numeric, hotspot, scenario, confidence, and open response.
- [x] Cover media and utility patterns: video, audio, animation, embedded
  interactives, documents, navigation hubs, dividers, resources, glossary,
  action plans, next steps, and credentials.
- [x] Index ready and planned concepts in the versioned `slide_templates_v3`
  Qdrant collection through the LiteLLM `component-catalog-embedding` alias.
- [x] Add deterministic ready-only production retrieval and a separate catalog
  discovery query.
- [x] Diversify candidate results by suggested implementation family so aliases
  do not crowd out structurally different designs.
- [x] Implement reusable `card_grid` variants: text, icon, numbered, and metric.
- [x] Implement reusable `callout_focus` variants: definition, statistic, quote,
  policy, and warning.
- [x] Implement reusable `structured_list` variants: checklist, numbered list,
  tips, agenda, and next steps.
- [x] Add all three families to the deterministic Docker-rendered gallery.
- [x] Verify representative catalog queries rank 2×2 matrix, open response, and
  audio concepts first while production retrieval excludes their planned forms.
- [x] Implement `paired_comparison` with before/after, pros/cons, do/don't, and
  current/future variants.
- [x] Implement `disclosure_list` with accessible accordion, FAQ, and ungraded
  click-to-reveal variants.
- [x] Implement `relationship_diagram` with cycle, hierarchy, continuum, 2×2
  matrix, and simple linear-flow variants.
- [x] Add explicit catalog-to-family readiness mappings and design guardrails.
- [x] Add topic-neutral fixture content for all twelve new variants and render
  it as a model-free Docker gallery.
- [ ] Implement `labeled_diagram` and `data_visualization` families.
- [ ] Implement practice interaction families, beginning with matching,
  sorting, ordering, and guided walkthrough.
- [ ] Implement additional assessment contracts without weakening source
  fidelity or accessibility.
- [ ] Add an offline judged-query evaluation set spanning every category,
  including expected, acceptable, and forbidden candidates.

## Phase 7 — Reliability, Observability, and Release Gates

Status: not started.

- [ ] Emit structured logs for selection, fitting attempts, violations,
  retries, model aliases, token usage, duration, and terminal failures.
- [ ] Never log API keys or full sensitive RLO payloads by default.
- [x] Add an opt-in live LiteLLM integration test marked separately from unit
  tests.
- [ ] Render at least two structurally different synthetic RLOs and verify
  different suitable archetypes are selected.
- [ ] Run all 22 committed RLOs as regression inputs without asserting that
  named methodologies map to specific layouts.
- [ ] Verify deterministic rerendering from saved normalized content.
- [x] Verify component gallery output without LiteLLM, Qdrant, or object
  storage.
- [ ] Verify the API still seeds and validates all committed RLOs.
- [ ] Document failure modes and operational retry behavior.

## Future — Slide-Level Design Orchestration

Revisit after the archetype and variant system is stable. The current course
planner chooses archetypes and the renderer applies deterministic variants.
A later orchestration layer may design individual slides independently and
execute those slide jobs in parallel batches.

- [x] Declare initial count- and image-aware layout variants in registry descriptors.
- [x] Render 2-3 flip cards as wide horizontal rows rather than a five-column grid.
- [x] Remove response collection from passive consideration prompts.
- [x] Add optional image splits for low-density objectives, rules, short processes,
  consideration prompts, and short takeaway lists.
- [x] Add a typed `layout_variant` decision when variants require agent judgment
  beyond deterministic item count and image availability.
- [x] Define a slide-job contract suitable for independent parallel execution.
- [ ] Evaluate whole-course coherence constraints before moving planning to
  fully independent slide agents.

## Docker Verification Checklist

Run these commands from the repository root. The exact test paths may expand as
phases are implemented, but these entrypoints remain the supported workflow.

- [x] Constraint tests:

  ```bash
  docker compose --profile generate run --rm --no-deps --build \
    --entrypoint pytest pipeline -q tests/test_constraints.py
  ```

- [x] All pipeline unit tests:

  ```bash
  docker compose --profile generate run --rm --no-deps --build \
    --entrypoint pytest pipeline -q tests
  ```

- [x] Shared-schema validation for every committed RLO:

  ```bash
  docker compose --profile generate run --rm --no-deps \
    --entrypoint python pipeline -c \
    "from pathlib import Path; import json; from rlo_schema import validate_rlo; files=sorted(Path('/course-definitions/rlos').glob('*.json')); [validate_rlo(json.loads(p.read_text())) for p in files]; print(f'{len(files)} RLOs validated')"
  ```

- [ ] API tests and seed smoke test:

  ```bash
  docker compose build api
  docker compose up -d minio qdrant litellm api
  ```

- [x] Component gallery renders without a model call.
- [x] Synthetic end-to-end service test passes without network access.
- [x] Opt-in live LiteLLM integration test shows at least one budget-driven
  `ModelRetry`.
- [x] `git diff --check` passes.
- [x] `git diff --name-only -- manim` produces no output.

## Definition of Done

The slide pipeline milestone is complete when:

- [ ] Any valid, supported v1 RLO shape can enter through the service contract.
- [ ] No application model call bypasses LiteLLM or uses a provider-specific
  SDK.
- [ ] Layout selection is based on generic instructional/structural evidence.
- [ ] Every generated screen is grounded in resolvable RLO source references.
- [ ] Every screen satisfies deterministic capacity checks or returns a clear,
  typed failure.
- [ ] Assessment feedback remains diagnostic and faithful to the RLO.
- [ ] All archetypes render without an LLM from gallery fixtures.
- [ ] Docker builds and all non-live tests pass from a clean checkout.
- [ ] The API continues to validate and seed the committed RLO catalog.
- [ ] No files under `manim/` have changed.
