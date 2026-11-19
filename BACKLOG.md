# Backlog

Deferred ideas and follow-up work encountered during implementation. Items here are not committed roadmap work and should be refined before being scheduled.

## RLO lifecycle and schema evolution

- **RLO revision history:** Allow learning admins to revise RLO content while retaining a stable RLO identity, prior revisions, authorship, and audit history.
- **RLO reprocessing:** Re-create an older RLO from its preserved sources, extraction artifacts, selected objectives, evidence, and generation metadata.
- **Schema migration strategy:** Introduce registered schema versions and migration tooling once the RLO framework becomes a production contract. Current prototype RLOs do not require backward compatibility.

## Source-processing quality

- **Curated extraction evaluation set:** If quality measurement becomes necessary, assemble a small, expert-reviewed corpus for observable extraction failures. Avoid attempting to automatically judge subjective Docling or chart-decoding quality without a trustworthy reference.

## RLO drafting operations

- **Asynchronous draft worker:** Move synchronous RLO generation behind the durable worker boundary when draft volume requires queue recovery, leases, and retry controls.
- **Model comparison:** Compare Luna with a stronger configured alias for drafting and review using a controlled corpus and instructional-designer acceptance data.
- **Structured RLO editor:** Replace advanced JSON editing with field-level authoring controls if learning-admin usage shows that the readable preview and decision workflow are insufficient.

## Learning-objective workflow hardening

- **Planning-unit checkpoints:** Persist individual objective-decomposition unit results so a failed multi-million-token job resumes after its last completed unit instead of rerunning objective model calls. Source-map units are already cached.
- **Large-corpus exercise:** Run a generated multi-million-token hierarchy through the worker to measure bounded-call coverage, checkpoint recovery, total candidate persistence, and review-page pagination.
- **Representative LDS review:** Have one Instructional Designer complete a real objective job and record missed or irrelevant objectives, assessment-boundary issues, lineage usability, and workflow friction before prompt tuning.
- **Visual browser pass:** Review the Objective Jobs and Objective Review pages at desktop and narrow breakpoints with representative high-volume results.
