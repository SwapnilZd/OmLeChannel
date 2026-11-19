# Omnichannel Learning – POC2 Readout

**Author:** Robert Taylor, AAI SGM
**Created:** September 22, 2026

*The Executive Summary will be completed after review of the findings and recommendations.*

## 2. Background and Scope

POC1 tested whether an automated pipeline could generate podcasts, narrated videos, and
e-learning modules from prepared Reusable Learning Objects (RLOs). POC2 tested the missing
upstream step: whether raw source content could be turned into the learning objectives and
RLOs that feed that pipeline.

The goal was to establish whether a source-to-RLO workflow is technically and conceptually
feasible. A user should be able to upload a document, review proposed learning objectives,
approve the objectives worth developing, review the generated RLOs, and publish approved
RLOs into the existing registry. The RLOs should remain traceable to their source, while
also containing enough instructional structure to support examples, practice, and
assessment.

POC2 was deliberately constrained to five combinations of content type and cognitive
level: Fact × Remember, Concept × Understand, Concept × Apply, Process × Understand, and
Procedure × Apply. These were the five combinations G&D identified as in scope for the
phase. POC2 did not attempt to implement every combination described in earlier materials,
nor did it test production-scale volume, a representative body of Deloitte source
material, or actual learner performance.

We set out with four practical questions:

1. Can the pipeline identify useful learning objectives from source content rather than
   relying on manually prepared RLOs?
2. Can it generate complete, reviewable RLOs while preserving source traceability?
3. Can L&D / G&D reviewers understand and control the workflow without working directly
   with prompts or structured data?
4. What would prevent this approach from operating at meaningful scale?

## 3. Approach

We approached POC2 as an end-to-end test rather than a demonstration built around one
hand-crafted output. Testers uploaded source documents through the application. The
pipeline extracted and organized the source content, proposed learning objectives, and
showed the source evidence associated with each objective. Reviewers could approve,
revise, or reject each objective before any RLO was generated.

For approved objectives, the pipeline produced a seven-part RLO covering the objective,
set-up, instruction, worked example, practice, assessment, and transfer back to work. It
then checked the result for source grounding and instructional alignment. Reviewers could
inspect the complete output, see which material came directly from the source and which
material had been added, request a bounded revision, reject the RLO, or approve and
publish it. Approved RLOs were stored in the registry and could be exported as structured
JSON for use outside the application.

The workflow was tested by L&D / G&D reviewers using the deployed POC. Feedback was
largely positive and supported the basic product concept. The reviewers also identified
examples where a classification appeared inconsistent with the content, where a
source-specific qualification had been broadened, and where practice activities were
repetitive. We treat those as useful evidence about the limits of the approach rather
than as a complete quality audit.

There was one important constraint on the evaluation. The supporting G&D materials did
not provide one consistent baseline. Some documents described 13 valid instructional
combinations, one tester comment referred to 18, and the agreed POC2 scope contained five.
Some detailed activity patterns were also treated in the feedback as mandatory pass/fail
rules, while the implementation treated them as guidance. The next phase will need one
agreed, versioned evaluation standard before its results can be interpreted cleanly.

## 4. Findings: Conceptual Feasibility

POC2 demonstrated that the source-to-RLO workflow is feasible. A document can be uploaded,
converted into candidate objectives, reviewed, authored into RLOs, checked against the
source, and published through one integrated application. The more important question is
not whether this can be done, but under what conditions it remains useful and manageable
at scale. Four findings shape that answer.

### 4.1 Source Content Availability

POC1 raised an open question about whether the intended topic universe is bounded. If
Deloitte has a finite and identifiable set of authoritative source materials, the problem
looks materially different from supporting any learning request a practitioner might
make. POC2 was expected to begin answering that question, but no representative body of
internal content was provided for the phase.

As a result, POC2 showed that the system can process source content; it did not show that
enough suitable content exists to support tens of thousands of practitioners. We do not
yet know how much material is current, authoritative, reusable, and available in a form
the pipeline can consume. We also do not know who would own the decisions to approve a
source, resolve conflicts between sources, apply regional or practice-specific variations,
or retire material when it becomes outdated.

This is more than a document-ingestion issue. The quality and coverage of the RLO library
will be bounded by the quality and coverage of the source library. Sparse source material
pushes the pipeline toward adding more knowledge. Conflicting or outdated material pushes
the problem into governance. Broad reference documents may contain many topics but still
lack the examples and practice needed to teach any one of them well.

The absence of representative content therefore leaves one of the central business
questions unanswered. Before considering broad deployment, we need to know whether the
content problem is a tractable, bounded library that can be inventoried and maintained or
an open-ended demand that the current source-governed model cannot reliably cover.

### 4.2 Human Review and the Operating Model

POC2 uses two human review gates. The first occurs after objective creation, before the
system spends time and money authoring an RLO. The second occurs after authoring, before
the RLO is published. Both gates proved useful. Reviewers could prevent an unsupported or
low-value objective from proceeding and could inspect the completed learning object before
it entered the reusable library.

The same controls create a significant operating constraint. Every source may produce
several objectives, and every approved objective may produce an RLO. If each one requires
detailed instructional review, human capacity rather than model capacity will determine
how much content can be produced. This is especially important because the review is not
purely mechanical. The tester feedback required judgment about whether a distinction was
at Understand or Apply, whether a source qualifier had been generalized too far, and
whether two practice activities provided enough progression.

The POC does not provide evidence that either review gate can be removed safely. It does
suggest that treating every item identically will be difficult to sustain. A production
model may need different review requirements based on source authority, content risk,
confidence, intended audience, or whether an RLO is new versus a minor update. Sampling
may be appropriate for some lower-risk content, while policy, regulatory, or methodology
content may always require explicit approval.

This also requires a resourcing decision. Human review cannot remain an assumed
contribution from L&D / G&D on top of other responsibilities if it is a required part of
the operating model. The work needs a named owner, a service expectation, and enough
capacity to keep pace with the volume the platform is expected to produce.

### 4.3 Grounding, Content Gaps, and Instructional Quality

The strongest improvement in POC2 is traceability. Reviewers can see the evidence behind
an objective and can distinguish source-derived material from knowledge or instructional
content added during authoring. This is a meaningful improvement over asking a model to
generate a learning object from a general prompt.

Source grounding does not, however, remove the need for judgment. Source documents are
rarely written as complete microlearning experiences. A strict transformation may remain
faithful to the document but produce something dry, literal, or overly dependent on the
source's structure. A more expansive transformation can create a stronger scenario or
assessment but risks making claims the source does not support.

The tester feedback included a useful example. A statement qualified within the Immunity
to Change framework was presented more generally in the generated instruction. The issue
was not fabrication in the usual sense; the output remained related to the source. The
problem was that the scope of the claim changed. This is exactly the kind of subtle issue
that source citations alone do not solve.

POC2 introduced content-gap enrichment because some objectives cannot be taught well from
the source text alone. The source may establish that a topic matters while omitting a
worked example, realistic case, explanation, or useful feedback. In those situations,
added domain knowledge can make the difference between a source summary and an actual
learning experience. It can also undermine the source-governed model if it is added too
freely or treated as equally authoritative.

The evidence supports retaining enrichment, but within a clearer policy. The system should
add content to address a specific instructional gap, not simply because additional detail
is available. Reviewers need to know what was added and why. Higher-risk additions may
need an identified authority or subject-matter review. We also need evidence from a
representative source set to understand how often enrichment is required; POC2 implemented
the capability but did not establish its expected use at scale.

### 4.4 Coherence and Learning Effectiveness

POC2 generated complete individual RLOs, but completeness does not guarantee a strong
learning experience. One tester identified an RLO whose label indicated Concept × Apply
while the objective and activity appeared closer to Concept × Understand. Another noted
that the practice section repeated the same interaction pattern without meaningfully
reducing support. The exact number of practice items was not a mandatory POC2 rule, but
the underlying concern is valid. The objective, instruction, practice, assessment, and
classification should all require the same learner performance.

There is a second coherence problem when RLOs are reused. Commissioning can retrieve
objects that are technically related to the same request, including objects developed
from different sources. Those RLOs may use different terminology, assume different prior
knowledge, repeat the same point, or leave gaps between one objective and the next.
Semantic relevance is not the same as instructional sequence. Individually acceptable
RLOs can still produce a disjointed course.

This makes pathway-level review a distinct requirement rather than an extension of RLO
review. The assembled experience needs to be checked for prerequisites, progression,
duplication, transitions, terminology, and cumulative assessment coverage. Otherwise,
modularity solves content reuse while moving the coherence problem downstream.

Finally, POC2 did not include learners. Positive L&D / G&D review supports the quality and
credibility of the product concept, but it does not establish comprehension, retention,
transfer, or performance improvement. We demonstrated authoring feasibility and expert
reviewability. Learning effectiveness remains a separate and necessary test.

## 5. Production and Tooling

### 5.1 Content Production Infrastructure

POC2 extended the existing generation platform rather than creating a separate prototype.
The application now retains the source, extracted content, proposed objectives, reviewer
decisions, generated RLOs, provenance, validation findings, revisions, and published
versions. A failed item can be retained for review without discarding other successful
results from the same batch. Model usage and cost can be traced by job.

The workflow is driven by shared rules and structured outputs rather than topic-specific
code. The same process can accept different source documents without manually rewriting
the application for each one. The five supported instructional combinations use different
authoring guidance, but the underlying workflow remains the same.

For production, the POC infrastructure would need the same hardening described in the
POC1 readout: managed storage and databases, identity and access control, secrets
management, monitoring, backup, recovery, CI/CD, and clear support ownership. POC2 adds
source governance, prompt and rule versioning, approval history, and published-content
versioning to that list. These are normal production-build requirements, but they are not
minor finishing work if the platform is expected to manage authoritative learning content.

### 5.2 Rules and Change Management

G&D provided extensive guidance covering content types, cognitive levels, RLO structure,
mapping, validation, and activity design. That material was useful, but it also demonstrated
the limit of treating detailed guidance as a literal generation specification. Forty-four
pages of overlapping rules cannot simply be placed into a prompt and expected to produce
stable, natural content. The result is likely to become repetitive, overfit to the rules,
or inconsistent when requirements compete.

For POC2, the material was reduced into a smaller authoring reference and then into
cell-specific guidance. Preferred activity shapes were treated as guidance rather than
absolute mandates. Source integrity, objective alignment, and valid assessment took
priority over mechanically satisfying every suggested feature.

A production process will need a controlled way to maintain those rules. Proposed changes
should identify the problem they solve, the outputs they affect, and how they will be
tested. The disagreement between five, 13, and 18 valid combinations is a simple example
of what happens when architecture, evaluation criteria, and implementation guidance are
not versioned together.

## 6. Operator Tooling

POC2 added an operator workflow for the people expected to review and govern the content.
Source Intake supports upload and extraction review. Objective Jobs shows proposed
objectives, source evidence, classification, and approval status. RLO Review presents the
complete learning object, source provenance, added knowledge, validation findings,
revision controls, and export. Approved RLOs appear in the Registry and can be used by the
Commission Learning workflow.

The UI changed materially during the phase. Early review pages exposed too many internal
fields and warnings without explaining which ones mattered. Draft export was unclear,
provenance sections did not remain open during refresh, and some validation language was
difficult to connect to the content it described. These issues were addressed during the
POC, and testers were able to complete the intended workflow.

The remaining question is how much evidence a reviewer needs by default. The platform can
show extensive lineage and diagnostic information, but displaying everything at once can
make the actual decision harder. A production design should distinguish three things
clearly: issues that block publication, questions that require human judgment, and
suggestions that may improve the content but do not make it invalid.

One tester also expected the review interface to show which RLO parts were fixed and which
were adaptive. The architecture materials describe that future behavior, but POC2 creates
a base RLO before it knows the eventual learner. Learner-specific adaptation therefore
belongs primarily to the later assembly and delivery process. The metadata and review
requirements for that capability should be defined when personalization is implemented,
rather than treated as an implicit POC2 defect.

## 7. Assessment Against Success Criteria

As in POC1, the evaluation material was not fully reconciled with the agreed scope before
testing. We therefore treat it as useful feedback rather than a single authoritative
pass/fail baseline. The assessment below uses the five-cell POC2 scope agreed before the
final implementation.

| Area | Assessment |
| --- | --- |
| Source intake | **Achieved with caveats.** The application accepted supported source formats and preserved extracted content for review. A representative Deloitte content set was not provided. |
| Objective generation | **Achieved.** The pipeline proposed source-supported objectives and exposed the evidence behind them. Classification boundary cases still require calibration and judgment. |
| Scope control | **Achieved.** Only the five agreed Content-Type × Bloom combinations could proceed into POC2 authoring. Out-of-scope objectives remained visible rather than being silently discarded or forced into a supported category. |
| Objective review | **Achieved.** Reviewers could approve, revise, reclassify, or reject objectives before RLO generation. The operating cost of doing this at scale remains unresolved. |
| RLO generation | **Achieved with caveats.** Approved objectives produced complete seven-part RLOs. Instructional strength and activity variety were not consistent in every reviewed example. |
| Source traceability | **Largely achieved.** Reviewers could inspect source lineage and distinguish added knowledge. One reviewed example showed that a source-specific qualifier could still be broadened during authoring. |
| Content-gap enrichment | **Partially achieved.** The workflow can add and label knowledge needed to support instruction, scenarios, and assessment. The authority and review policy for this material has not been established. |
| Automated validation and revision | **Achieved with caveats.** The system produced grounding and instructional findings and supported bounded revision. The threshold between a blocking issue and a reviewer advisory remains a policy decision. |
| Publication and export | **Achieved.** Reviewers could approve and publish an RLO, store it in the Registry, and export the RLO and review metadata. |
| Reuse through commissioning | **Partially achieved.** Published RLOs were available for retrieval and content generation. The coherence of experiences assembled from multiple RLOs and sources was not established. |
| Production scale | **Not demonstrated.** POC2 did not test a representative source library, sustained review volume, or enterprise operating model. |
| Learning effectiveness | **Not evaluated.** The phase did not include learners or measure comprehension, retention, transfer, or workplace performance. |

Our overall assessment is that POC2 met its core technical-feasibility objective. It
demonstrated a usable source-to-RLO workflow and received a largely positive response from
the intended expert reviewers. It did not establish that the workflow can cover Deloitte's
learning demand at scale, reduce total human effort, or produce measurably effective
learning without continued instructional oversight.

## 8. Risks and Open Questions

**Risk: There may not be enough governed source material to support the intended demand.**
POC2 demonstrated processing, not content availability. Without an inventory, we cannot
tell whether the platform would support a bounded set of high-value subjects or face a
large volume of requests for which no approved source exists.

**Risk: Human review becomes the production bottleneck.** The current workflow assumes
review of both objectives and completed RLOs. That is appropriate for a POC and may remain
necessary for higher-risk content, but it is unlikely to support broad production volume
without dedicated capacity and a differentiated review model.

**Risk: Added knowledge weakens the source-authority model.** Enrichment is necessary when
a source supports an objective but not a complete learning experience. Without a clear
policy, the platform could gradually shift from source-grounded authoring toward model-led
content creation without an agreed authority for the added claims.

**Open question: Who owns coherence above the RLO level?** RLO authorship, retrieval, and
course assembly are separate steps. The current design does not yet establish who or what
is responsible for ensuring that the assembled pathway teaches one coherent progression.

**Open question: What quality standard predicts learning?** Detailed methodology rules can
improve consistency, but expert preference and learner effectiveness are not the same
measure. We need evidence about which activity and assessment patterns produce better
understanding and transfer before turning more preferences into mandatory controls.

## 9. Recommendations and Path Forward

### 9.1 Inventory a representative source library

Select a bounded set of real internal content across several domains, source types, and
owners. Confirm authority, permission, currency, and maintenance responsibility. Use this
set to measure how many useful objectives can be supported, how often enrichment is
needed, how much review each RLO requires, and what the true cost per approved RLO is.

This is the most important next step because it determines the shape of the opportunity.
If the source universe is bounded, the organization can pre-generate and review a core
RLO library and reserve real-time generation for genuinely contextual needs. If it is
effectively unbounded, the source-governed model and current review process are unlikely
to provide broad on-demand coverage.

### 9.2 Define the content authority and enrichment policy

Agree on what the source must support, what instructional transformation is allowed, what
types of knowledge may be added, and when an external authority or subject-matter expert
is required. Define which grounding findings automatically block publication and which
require reviewer judgment. Retain visible provenance as a core product capability.

### 9.3 Resource and test a scalable review model

Assign named instructional-design capacity to the next phase rather than treating review
as an occasional consultation. Measure review time, disagreement, revision frequency, and
defect escape rates. Use that evidence to determine whether trusted sources, low-risk
content, sampling, or confidence thresholds can safely reduce review effort. Do not remove
the current gates based on model confidence alone.

### 9.4 Evaluate pathways and learners, not only individual RLOs

Test realistic commissioned experiences containing RLOs from more than one source. Review
prerequisites, sequence, terminology, duplication, transitions, and assessment coverage.
Then place a small number of representative experiences in front of learners and compare
them with a credible baseline. Measure comprehension, usability, retention, and a
near-term application task.

### 9.5 Reconcile the requirements before the next gate

Create one versioned statement of scope, taxonomy, mandatory requirements, preferred
guidance, and future capabilities. Calibration examples should cover the most disputed
classification and grounding boundaries. Tester findings should distinguish an observed
output issue from a proposed design change. This will make the next readout an assessment
against an agreed baseline rather than an interpretation of several competing documents.

## 10. Appendix

**Reusable Learning Object (RLO):** A structured, self-contained unit of learning content
designed to teach and assess one specific performance. In POC2, an RLO combines approved
source material, instructional support, examples, practice, and assessment while retaining
the origin of substantive content.

**POC2 authoring scope:** Fact × Remember, Concept × Understand, Concept × Apply, Process ×
Understand, and Procedure × Apply.

**Interpretation of tester findings:** The classification-label and repetitive-practice
comments are retained as instructional-alignment observations. The source-scope comment is
retained as a grounding example. Adaptive-part visibility is treated as a future
personalization question. The suggestion that the success criteria should use 18 cells is
not treated as a product defect because the agreed POC2 scope contained five.
