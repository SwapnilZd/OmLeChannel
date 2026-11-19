# Corporate E-Learning Design Notes

## What the catalog represents

`catalog/corporate_elearning.yaml` is an instructional-use inventory. A catalog
concept describes the learner need in retrieval language; it is not necessarily
a unique HTML template. Several concepts can be served by one implementation
family and variant.

Production selection searches only registry descriptors whose indexed status is
`ready`. Catalog records remain discovery-only even when their `implementation`
mapping points to a ready family. The ready family descriptor is the production
search result; this prevents a catalog alias from being mistaken for a
`ScreenType`.

## Readiness mapping

Use this structure on a catalog concept when its design has been reviewed:

```yaml
implementation:
  status: ready
  family: paired_comparison
  variant: before_after
  notes: Requires exactly two corresponding source-grounded states.
```

Statuses:

- `ready`: model, descriptor, renderer, styles, preview data, and production
  retrieval record exist.
- `partial`: a related family exists, but an important behavior or content
  contract is missing.
- `planned`: no production-safe mapping exists yet.

## Implemented design families

### Card grid

Variants: `text_cards`, `icon_cards`, `numbered_cards`, `metric_cards`.

Use for concise peer items that remain visible together. Two cards use a
centered two-column composition; four use a two-by-two composition. Do not use
for ordered procedures or substantial definitions.

### Focused callout

Variants: `definition`, `key_stat`, `expert_quote`, `policy`, `warning`.

Use sparingly for one dominant message. Statistics and quotations must be
present in the source and retain attribution where supplied. Policy wording
must not be softened merely to satisfy presentation preferences.

### Structured list

Variants: `checklist`, `numbered_list`, `tips`, `agenda`, `next_steps`.

Use for label-and-detail items without a richer relationship. A checklist is
independent; an ordered process belongs in `process_sequence`.

### Paired comparison

Variants: `before_after`, `pros_cons`, `do_dont`, `current_future`.

Use only for exactly two meaningful sides. Preserve the source semantics:
trade-offs are not correct/incorrect, and a future state is not evidence that a
transformation has already occurred.

### Disclosure list

Variants: `accordion`, `faq`, `click_reveal`.

Uses native HTML disclosure controls for keyboard and assistive-technology
support. Do not hide critical information solely to reduce apparent density.
FAQ is appropriate only for genuinely question-shaped source content.

### Relationship diagram

Variants: `cycle`, `hierarchy`, `continuum`, `matrix_2x2`, `linear_flow`.

The visual relationship must be explicit in the RLO. Never invent hierarchy,
axis values, cyclic behavior, or ordering. The DOM retains a meaningful text
sequence if CSS is unavailable. `linear_flow` does not cover branching or
converging flows; those remain planned.

## Preview execution

`components/fixtures/corporate_designs.yaml` contains topic-neutral sample data
for every variant in the three newest families. Render it without a model call:

```bash
docker compose --profile generate run --rm --no-deps --build \
  --entrypoint python pipeline src/design_gallery.py \
  --out /generated/corporate-design-gallery.html
```

Preview content is illustrative and is never indexed as course knowledge. Only
descriptor retrieval text and compact eligibility metadata are embedded in
Qdrant.
