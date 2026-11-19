# Prompt Tuning & Standardization Plan

## Context

A full review of the 12 system prompts (2026-07) found tuning debt in five areas:
version bookkeeping, duplicated boilerplate, catalog-derived enums drifting from
code, semantic/structural leaks, and missing narration↔duration coupling. A
separate production defect confirmed the narration issue concretely: 45+ seconds
of narration attached to a title fade-in, because Manim voiceover blocks stretch
a single `.play()` to the full TTS duration.

This plan sequences the fixes. Each workstream is independently shippable.

**Status (2026-07-28): enacted.** WS1–WS6 and WS8 are complete, plus the prose
half of WS7. Remaining: WS7's contract change (move `width`/`height`/
`render_capability` out of `VideoProductionDraft` into the builder) — scheduled
with the next video-pipeline change. Notes from enactment:

- WS5 took Option B: filenames carry no version (`course_author.md`); the
  `PROMPT_VERSION` constant + the file's header line own versioning, enforced
  by `tests/test_prompt_versions.py`. All changed prompts were version-bumped.
- WS6 loader lives at `src/learning_pipeline/prompts/loader.py`
  (`{{include:shared/….md}}`, one level, header lines stripped). Shared blocks:
  `deloitte_style.md`, `personalization_boundary.md`, `teaching_patterns.md`,
  `learner_facing_content.md`. All 11 prompt consumers load via `load_prompt`.
- WS2 L3 required a controller change: `ManimBindingValidationError` routes
  binding/word-budget failures through the existing bounded repair loop at
  draft-resolution time (`_controller.py` step 3). Template guarantees are
  locked in by `tests/tools/manim_video/test_templates.py`.

**Previously done (2026-07-28):**

- All prompts unified under `src/learning_pipeline/prompts/` (the root `prompts/`
  folder is gone). Root-level prompts were not shipped in the wheel
  (`pyproject.toml` packages only `src/learning_pipeline`), so installed
  deployments would have been missing every planner prompt.
- Eight `_DEFAULT_PROMPT_PATH` constants repointed; two tests now import the
  planner's own path constant instead of re-deriving it.
- `docs/prompt-catalog.md` paths updated.

---

## WS1 — Correctness fixes (internal contradictions)

Small, high-confidence edits. Do these first.

| Fix | File | Detail |
|---|---|---|
| Restore `activate_prior_knowledge` to the output-schema role enum | `prompts/modality_planner/video.md` | Line ~168 omits a role that line ~56 declares valid. A schema-following model will never use it. |
| Fix the nesting-constraint sentence | `prompts/manim_render/scene_draft.md` | "component_bindings must be a flat or one-level-deep object" contradicts the prompt's own `chess_board` schema (`steps[].actions[]`). Reword to permit the documented two-level shapes. |

**Acceptance:** each prompt is internally consistent; no rule contradicts a
schema example in the same file.

---

## WS2 — Manim narration pacing (production defect)

### Problem

Every template renders voiceover beats as:

```python
with self.voiceover(text=...) as tracker:
    self.play(FadeIn(...), run_time=max(0.8, tracker.duration))
```

The animation itself is stretched to the narration length. A 45-second
`scene_narration` produces a 45-second crawling title write. Nothing upstream
teaches the LLM that each narration string maps 1:1 to one visual beat, or that
different beats can carry different amounts of speech.

### Fix — three layers

**Layer 1: bounded elasticity + staged motion (all 12 templates).**
Do NOT fully decouple animation from narration — a snap-reveal followed by a
long static hold reads as PowerPoint-with-voiceover, not an animated video.
Instead, each beat distributes the narration duration across a sequence of
animation stages, each with its own natural bounds:

```python
with self.voiceover(text=...) as tracker:
    d = tracker.duration
    self.play(FadeIn(bg_0),   run_time=_rt(d, 0.25, 0.5, 1.0))   # frac, min, max
    self.play(Write(lbl_0),   run_time=_rt(d, 0.30, 0.6, 1.8))
    self.play(FadeIn(det_0, shift=UP*0.1), run_time=_rt(d, 0.25, 0.5, 1.2))
    self.wait(max(0.0, d - elapsed))
```

For a typical 6–10 s beat, motion covers ~80 % of the speech. For an overlong
beat, stages hit their caps and the tail is a hold — after three distinct
movements, not one frozen frame or a 45-second crawling primitive.

Beats are classified by how well they absorb time:

- **fixed** (single primitive: title write, card fade): tight caps (~2.5 s max
  total motion) — stretching these is what produces the crawl defect;
- **medium** (item reveal with label + detail): staged as above (~4 s max);
- **elastic** (inherently sequential: chess move chains, cycle arrow rotation,
  lagged item cascades, highlight sweeps): high caps or true proportional
  scaling — more time makes these better, not worse.

The `_rt(duration, fraction, lo, hi)` helper is emitted into the generated
source from `manim/templates/_shared.py` so all templates share one timing
model. Word budgets (Layers 2–3) remain the primary control; elasticity is
graceful degradation, not the plan.

Files: `manim/templates/_shared.py` (timing helper),
`manim/templates/*/template.py` (all 12 `render()` functions).

**Layer 2: teach the mechanic and word budgets in the scene-draft prompt.**
Add a "Narration pacing" section to
`prompts/manim_render/scene_draft.md`:

- Each narration string is spoken over exactly one visual beat; the visual
  holds until the narration finishes.
- TTS speaks ≈ 2.5 words/second. Budget words per beat by beat type:
  - opener / title reveal: ≤ 25 words (~10 s) — the visual is simple; long
    speech over it feels stalled
  - per-item reveal: ≤ 45 words (~18 s) — these carry the teaching load
  - closing: ≤ 30 words (~12 s)
- Total words across all narration fields ≈ `target_duration_seconds × 2.5`.
  Distribute narration across item beats rather than front-loading the opener.

**Layer 3: schema + validate() word budgets.**
State per-field word budgets in each template `_SCHEMA` (e.g. "1–2 sentences,
max ~25 words"). In `validate()`, raise a validation error (not truncation)
when a narration field exceeds ~2× its budget — the error feeds the existing
bounded LLM repair loop. Narration is never silently truncated: a mid-sentence
TTS cut is worse than one repair round.

Files: `manim/templates/*/template.py` (`_SCHEMA` + `validate()`),
`manim/templates/_shared.py` (shared word-count helper).

**Acceptance:** rendered scenes show no animation stretched beyond ~1.5 s; a
draft with a 45-second opener narration fails validation and is repaired; total
narration duration tracks `target_duration_seconds` within ~20 %.

---

## WS3 — De-hardcode catalog-derived enums

### Problem

`prompts/modality_planner/elearning.md` hardcodes all 13 affordance IDs in
its output-schema example while also instructing "use only the `affordances`
list provided". The IDs currently match `affordances/elearning.py`, but the
next catalog change drifts silently — the same failure class as the stale Manim
binding schemas fixed in July 2026.

### Fix

- Remove literal affordance-ID enumerations from schema examples; replace with
  `"<id from the affordances list in the payload>"`.
- Keep the per-affordance "Use X when…" guidance prose, but add a comment at
  the top of that section: the payload's `affordances` list is authoritative;
  guidance here describes usage, not availability.
- Add a contract-consistency test (pattern already exists in
  `tests/tools/elearning/test_contract_consistency.py`) asserting that any
  affordance ID mentioned in the prompt exists in the catalog — so remaining
  prose mentions can't go stale undetected.

Files: `prompts/modality_planner/elearning.md`,
`tests/tools/elearning/test_contract_consistency.py` (or a new
`tests/planners/modality/test_prompt_consistency.py`).

**Acceptance:** no prompt contains an enumerated affordance-ID list in a schema
example; a test fails if a prompt mentions an affordance ID missing from the
catalog.

---

## WS4 — Narration↔duration coupling in workflow prompts

### Problem

- Podcast workflow states 150 wpm; video workflow states 130 wpm; the
  difference is unexplained.
- The e-learning workflow prompt has **no** rate guidance at all for
  `narration_script` in avatar/Manim directives, and no coupling to
  `target_duration_seconds`. This is the upstream source of overlong Manim
  narration (see WS2).
- Manim guidance is one stale line ("abstract visualizations, mathematical
  animations, and process flows") that predates the 12-template catalog.

### Fix

- Add to `prompts/workflow_planner/elearning.md`:
  - narration budget: `target_duration_seconds × 2.5 words` per directive
    (state the wpm assumption explicitly);
  - visual-pattern guidance for `animation_direction` — describe the patterns
    that render well *without naming template IDs* (layer boundary): enumerated
    lists/steps, hub-and-spoke concept maps, two-column comparisons, timelines,
    circular/iterative cycles, process flows with arrows, 2×2 matrices,
    term-definition breakdowns, hierarchy pyramids, myth-vs-reality pairs,
    decision scenarios.
- Standardize the wpm figure or document the difference (dialogue vs.
  presentational delivery) in each prompt that states one.
- Replace "prefer 3–5 screens per instructional beat" with a concrete unit
  ("per modality scene").

Files: `prompts/workflow_planner/elearning.md`,
`prompts/workflow_planner/podcast.md`,
`prompts/workflow_planner/video.md`.

**Acceptance:** every prompt that requests spoken text states a words-per-second
budget tied to the duration field the LLM controls.

---

## WS5 — Version bookkeeping

### Problem

Every prompt file is named `_v1.md` while the `PROMPT_VERSION` constants
recorded in traces have moved on (`course_author_v4`, `elearning_v3`,
`podcast_modality_v3`, `manim_scene_draft_v2`, `course_assembly_v2`,
`learner-facing-content-v2`, …). A trace version can no longer be matched to a
file; git archaeology is the only recovery path.

### Fix (decision required)

Option A — **filename tracks the constant** (rename on every bump). Keeps the
"versioned prompt file" promise; noisy diffs.

Option B — **drop version from filenames** (`course_author.md`); the constant +
git history own versioning. One-time rename; prompt-path constants stop
churning. **Recommended** — matches how the constants are already being used.

Either way: add a consistency test that each module's `PROMPT_VERSION` change
requires a matching change in the prompt file's header line, so the constant
can't be bumped without touching the file (or vice versa).

Files: all 12 prompts, 10 `PROMPT_VERSION` sites, `docs/prompt-catalog.md`.

**Acceptance:** a trace's `prompt_version` unambiguously identifies prompt
content (via filename or via header + git); a test enforces the pairing.

---

## WS6 — Shared charter composition

### Problem

`prompts/shared/learner_facing_content.md` is loaded by no code — only its
version string is hashed. Its text is hand-copied into `course_author.md`
and paraphrased in all three workflow prompts. The Deloitte style paragraph and
the personalization-boundary paragraph are duplicated across 4–6 prompts each,
already with wording drift.

### Fix

Introduce a tiny prompt-composition step at load time: prompts may contain
`{{include:shared/learner_facing_content.md}}` markers resolved by the loader
(one function, no templating engine). Move the two shared paragraphs into
`prompts/shared/` and replace the copies with includes. The composed text is
what gets hashed into `prompt_version` traces, so caching semantics are
unchanged.

If composition is judged not worth it, the fallback is to delete
`shared/learner_facing_content.md` and accept duplication — but then remove
`CONTENT_CHARTER_VERSION` hashing of a file that nothing reads.

Files: new loader helper (e.g. `src/learning_pipeline/prompts/loader.py`), all
prompts containing the duplicated paragraphs,
`tools/elearning_bundle/_authoring_workspace.py`.

**Acceptance:** shared boilerplate exists in exactly one file; every consumer
composes it; no dead prompt files remain.

---

## WS7 — Structural leaks and stale references

### Problem

- `prompts/workflow_planner/video.md` asks the LLM to output `width`,
  `height`, and echo `render_capability: "video.avatar.render"` — structural
  constants that the deterministic builder should own (the e-learning builder
  already owns 1920×1080). The prompt example even shows a different resolution
  (1280×720).
- Roadmap references leak into prompts: "For Phase 13B, prefer solid brand
  colours" (video workflow), "image generation is disabled by default in Phase
  14B" (course author).

### Fix

- Remove phase references from prompts (pure prose edits, no risk).
- Move `width`/`height`/`render_capability` from `VideoProductionDraft` LLM
  output to builder-owned constants. This is a contract change: update
  `contracts/planning.py`, `planners/workflow/video/builder.py`, validation,
  and the prompt. Schedule with the next video-pipeline change rather than
  standalone.

**Acceptance:** no prompt mentions an internal phase number; the video LLM
output contains no fixed-constant fields.

---

## WS8 — Vocabulary standardization (lower priority)

- **`teaching_pattern`**: three prompts present three different
  pseudo-enumerations of this free-text field. Define one shared vocabulary
  (likely in `prompts/shared/`, composed per WS6) used by all modality
  planner prompts, since workflow planners must implement whatever vocabulary
  the modality planner emits.
- **"Return only JSON" instructions**: present in podcast/video prompts, absent
  in e-learning ones. Structured-output enforcement makes these redundant —
  standardize (either keep one canonical sentence everywhere or drop them).
- **Curriculum duration arithmetic**: `course_assembly.md` asks the LLM to
  compute `ceil(base × proportion × depth × gap)` across every RLO. Ask for the
  per-RLO estimate to be emitted in a draft field so deterministic validation
  can recheck the arithmetic instead of trusting it.
- **Format selector** (`auto.md`): thin but low-stakes (advisory role,
  deterministic fallback). Add brief guidance on weighing deterministic scores
  vs. pedagogical judgment when convenient.

---

## Suggested sequencing

| Order | Workstream | Rationale |
|---|---|---|
| 1 | WS1 | Five-minute contradiction fixes; unblock correct model behavior |
| 2 | WS2 | Live production defect (narration over title fade); deterministic layer lands first |
| 3 | WS4 | Upstream cause of WS2; small prompt edits |
| 4 | WS3 | Drift class with a proven failure history |
| 5 | WS5 | Decision + mechanical rename; do before further prompt tuning bumps versions again |
| 6 | WS6 | Requires the loader; do after WS5 settles naming |
| 7 | WS7 | Contract change rides the next video-pipeline work |
| 8 | WS8 | Cleanup; fold into WS6's shared-vocabulary file where possible |
