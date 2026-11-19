# Objective + Seven-Part Source Review

## Status

Implementation in progress. This design supersedes the
separate `detail_enrichment` and `detail_review` human-review path described in
the earlier objective extraction plan.

Canonical rule reference:
[RLO Generation Rules — Consolidated Reference](rlo-generation-rules-reference.md)

## Goal

Give an LDS Instructional Designer one place to decide whether a proposed
enabling objective is worth retaining while seeing what source-native material
may help build the eventual RLO.

The reviewer approves, edits, rejects, splits, merges, or adds the **objective**.
The seven-part view is supporting evidence, not a second approval task and not a
claim that an RLO has already been authored.

## Observable outcome

For every objective candidate, the review screen shows:

1. the atomic enabling objective and its Deloitte practitioner relevance;
2. advisory content-kind and Bloom-level hints;
3. objective-defining source lineage; and
4. an ordered Cover → Set-up → Teach → Show → Practice → Check → Send-off
   source-availability view with evidence for every positive finding.

After every candidate has a decision, one action finalizes the approved set and
produces an objective package ready for future RLO planning. There is no separate
human source-mapping or detail-review gate.

## Product decisions

### What is being reviewed

- The human decision applies to the objective, not to extraction quality or each
  individual RLO part.
- Approving an objective means: “This is a useful, appropriately scoped learning
  objective we may build into an RLO.”
- Approval does not certify the suggested classification, source coverage, or a
  future authored RLO.
- Rejected objectives and prior revisions remain auditable.

### What the seven-part view means

The view reports **source availability**, not schema completeness:

| Status | Meaning |
| --- | --- |
| Found | At least one source-native feature associated with this objective was explicitly observed for this part. |
| Possible | Relevant material may be present, but its purpose or association requires interpretation. |
| Not found | The extraction and feature-inventory passes did not identify associated source material for this part. This is not proof that the material does not exist. |

The UI must not use `Complete`, `Passed`, or `Approved` for these statuses. Formal
completeness is cell-specific and cannot be established until later RLO planning
selects a target schema.

### What classification means

- Content kind and Bloom level remain visibly labeled **Suggested**.
- They encourage useful variety and support discussion during objective review.
- They do not constrain the future RLO. Later planning selects a target cell, and
  validation of a completed RLO observes the performance it actually contains.

## Seven-part projection

The first vertical slice should project the existing source-feature inventory
into the seven-part view. This avoids a new model call merely to relabel evidence.
A feature can appear in more than one part when its source function genuinely
supports both.

| RLO part | Existing source-feature signals |
| --- | --- |
| Cover | Always available from system-known objective identity, source provenance, review metadata, and advisory classification; an `explicit_objective` adds source-native support but is not required |
| Set-up | `explicit_objective`, `prerequisite_transfer`, and source-native context that establishes a moment of need |
| Teach | `core_substance`, `structured_visual` |
| Show | `worked_example` |
| Practice | `practice_activity` |
| Check | `assessment` |
| Send-off | `prerequisite_transfer` |

`currency_signal` remains an objective-level warning rather than pretending to
fill an RLO part.

### Status aggregation

For each objective and part:

1. mark Cover `Found` because the system already has the objective identity, source
   provenance, review metadata, and advisory classification;
2. for the other six parts, consider only source features associated with that objective;
3. `Found` if one or more associated features are `observed`;
4. otherwise `Possible` if one or more are `uncertain`;
5. otherwise `Not found`;
6. preserve all matching feature IDs and source evidence rather than selecting a
   single “best” passage.

This aggregation is deterministic. It does not assess pedagogical quality.

### Association integrity

The current feature-inventory call runs before candidates exist, so a feature
cannot reliably provide candidate IDs. Candidate-to-feature association should
therefore be owned by candidate formation and verified in application code:

- candidate formation may return IDs only from the source features supplied in
  its structured input;
- application code rejects unknown feature IDs;
- exact overlap in cited claim or node IDs may add a deterministic association;
- a feature with no defensible objective association remains visible at job level
  as “Unassociated source material” and must not be forced into a candidate;
- all positive part statuses resolve to at least one real source node.

This is sufficient for the POC. A separate semantic-association prompt should be
added only if representative review shows that exact evidence association misses
material that reviewers need.

## Component design

### Page hierarchy

```text
Objective + Source Review
├── Job summary and processing status
├── Review progress: decided / total
├── Objective list and filters
└── Selected objective
    ├── Objective statement and practitioner relevance
    ├── Suggested kind, Suggested Bloom, confidence
    ├── Approve / Edit / Reject / Split / Merge / Add related
    ├── Objective-defining source evidence
    ├── Source availability — seven ordered rows
    │   ├── Cover
    │   ├── Set-up
    │   ├── Teach
    │   ├── Show
    │   ├── Practice
    │   ├── Check
    │   └── Send-off
    └── Secondary details
        ├── rationale, assumptions, prerequisites, and warnings
        ├── unassociated source material
        ├── prompts used
        └── job history
```

### Seven-part row

Each row contains:

- ordinal and stable name, such as `3 · Teach`;
- `Found`, `Possible`, or `Not found` status;
- a short factual summary of the material found;
- evidence count and source locations;
- an expandable evidence area containing excerpts and “Open original” links; and
- an explicit “No associated material surfaced” message when not found.

Rows stay in canonical order on all screen sizes. On narrow screens, row metadata
wraps beneath the name; the evidence control remains keyboard-operable. Color is
not the only status indicator.

### Primary and secondary emphasis

The objective decision remains visually primary. Seven-part availability is the
next section in the main reading column, not a detached sidebar. Prompts, history,
unassociated features, detailed rationale, and assumptions are progressive
disclosures so they do not compete with the decision.

### Review progress

The page reports, for example, `18 of 24 decided · 14 approved · 4 rejected · 6
remaining`. The finalization action remains disabled until every current candidate
is Approved or Rejected. `Revision requested` and `Pending` are unresolved states.

## Data contract

### Existing canonical records

Keep these as the source of truth:

- `ObjectiveCandidate` for the objective and advisory hints;
- `SourceFeature` for extracted source-native material;
- `ObjectiveEvidence` for claim/node lineage;
- `source_feature_ids` on the candidate for associations; and
- objective review records for the human decision history.

Do not persist duplicate seven-part status rows in the first slice. They are a
deterministic API projection of versioned workspace data and can be reproduced.

### Candidate response addition

Add an ordered `part_availability` field to the candidate API response:

```json
[
  {
    "part": "teach",
    "ordinal": 3,
    "label": "Teach",
    "status": "found",
    "summary": "The source explains the incident-response lifecycle and its phases.",
    "source_feature_ids": ["feature-123"],
    "evidence_count": 2,
    "evidence": []
  }
]
```

The API returns all seven entries even when every status is `not_found`. Evidence
uses the existing resolved lineage shape; it should not introduce another locator
contract.

### Completed package

The completed objective package contains only candidates whose latest
**objective** review is Approved. It includes the source-feature inventory and
candidate associations so future RLO planning can reproduce the availability view.
It must not depend on a detail-review record.

## Workflow

### Target workflow

```text
Draft / processing
    ↓
Objective + source review
    ↓ all candidates decided; reviewer finalizes set
Complete — ready for RLO planning
```

`objectives_approved`, `detail_enrichment`, `detail_review`, and
`details_approved` should not remain as user-visible clicks. Because these jobs are
POC artifacts, no compatibility adapter is required for disposable historical
jobs. The migration must still leave the database schema valid and deterministic
for a fresh deployment.

### Transition rules

- Model processing completion moves `draft` to `objective_review`.
- Candidate decisions are permitted only in `objective_review`.
- Objective edits create a new workspace revision and invalidate decisions affected
  by that revision under the existing optimistic-concurrency behavior.
- Finalize is allowed only when all current candidates are Approved or Rejected.
- Finalize moves directly to `complete`, timestamps the job, and records actor,
  approved/rejected counts, workspace revision, and an event.
- Future RLO planning consumes the completed package; it is outside this slice.

## API and UI changes

### API

- Add deterministic seven-part projection to candidate serialization.
- Make candidate formation own `source_feature_ids` and validate associations.
- Permit any intended objective-and-association edits during the single review
  stage; do not retain fields editable only during `detail_review`.
- Simplify review kind to the objective decision used by this workflow.
- Simplify the advance/finalize transition and completed-package selection.
- Preserve existing prompt-run, event, evidence, pagination, filter, and Excel
  export behavior.

### UI

- Rename the page to **Objective + Source Review**.
- Replace the seven-stage timeline with Discovery → Review → Ready for RLO planning.
- Put the ordered seven-part component in the selected objective's main column.
- Remove “Begin detail enrichment,” “Approve reviewed details,” and “Complete
  objective job” clicks.
- Rename the final action **Finalize approved objectives** and explain why it is
  disabled when decisions remain.
- Retain advisory hints, exact lineage, prompt inspection, history, and accessible
  objective actions.
- Keep unassociated source features available in a secondary job-level panel.

## Prompt impact

Update the clearly named prompt assets rather than adding inline prompt text:

- `source_feature_inventory.md`: remove the impossible expectation that the
  pre-candidate feature pass can know candidate IDs.
- `candidate_formation.md`: require zero or more known `source_feature_ids` per
  candidate and explain that these are source associations, not completeness.
- increment prompt versions and update `docs/prompt-catalog.md`.
- preserve exact prompt/input snapshots on every job as today.

No new “seven-part completeness” prompt belongs in this slice.

## Acceptance criteria

- [x] Every candidate API response has exactly seven ordered availability entries.
- [x] `Found` and `Possible` entries resolve to cited source nodes.
- [x] `Not found` is phrased as a search result, not proof of absence.
- [x] The seven-part projection is deterministic for a workspace revision.
- [x] Objective review visibly labels Bloom and content kind as suggestions.
- [x] A reviewer can approve, edit, reject, split, merge, and add a related objective.
- [x] The final action is blocked while any candidate remains pending or revision-requested.
- [x] Finalizing uses objective decisions and produces a completed package directly.
- [x] No second human detail-review stage appears in the active API workflow or UI.
- [x] Rejected candidates, edits, prompt snapshots, and review events remain auditable.
- [ ] Desktop and narrow layouts preserve part order and keyboard operation.
- [ ] Containerized contract, transition, route, and browser smoke tests pass.

## Phased implementation

### Phase A — Contracts and deterministic projection

- [x] Add the seven-part projection type and feature-to-part mapping.
- [x] Add validated candidate-owned feature associations.
- [x] Return resolved part evidence from the candidate endpoint.
- [x] Add unit tests for status aggregation, multi-part reuse, unassociated features,
  unknown IDs, and lineage requirements.

### Phase B — Single-gate workflow

- [x] Collapse the active job stages to Draft → Objective Review → Complete.
- [x] Make completion depend on objective decisions only.
- [x] Update package generation and transition/audit tests.
- [x] Remove obsolete detail-enrichment worker behavior and mark its prompt deprecated.

### Phase C — Review component

- [x] Build the ordered, expandable seven-part availability component.
- [x] Reorganize the page around the objective decision and component.
- [x] Add clear progress/finalization behavior and disabled-state explanation.
- [ ] Verify desktop, narrow, keyboard, and screen-reader semantics in Docker.

### Phase D — Representative review

- [ ] Run one representative public source through the full slice.
- [ ] Record whether associations and summaries help the LDS reviewer decide on
  objectives without implying extraction approval.
- [ ] Tune only demonstrated association or usability problems.

## Explicitly deferred

- Selecting a binding RLO cell.
- Retrieving and applying a complete cell-specific schema or methodology.
- Judging pedagogical completeness of any RLO part.
- Generating missing Teach, Show, Practice, Check, or Send-off content.
- Validating or approving a completed RLO.
- Learner-specific personalization and pathway assembly.
- Bank-wide deduplication and reprocessing old prototype RLOs.
