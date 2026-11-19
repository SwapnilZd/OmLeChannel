# Phase 2 Source-Material Review

## Purpose

This review evaluates the files collected in `/Users/roberttaylor9/Desktop/E-learning/Sources` against the agreed Phase 2 use case: testing whether the system can create candidate RLOs from factual source material at scale, without relying on course assets that people have already selected, sequenced, contextualized, or designed for instruction.

This is not a judgment about whether the files contain accurate facts or whether they were originally supplied by SMEs. A document can contain factual information and still be an instructional or course-development artifact. For this POC, that distinction matters because instructional artifacts disclose many of the decisions the system is supposed to make: what matters, who should learn it, the intended outcomes, the sequence, the examples, and how learning should be assessed.

## Working classification test

A suitable primary source for this test should generally:

- exist independently of the course-development effort;
- establish or explain substantive domain knowledge;
- retain identifiable provenance, authority, and version information;
- not already contain a course structure, learning objectives, assessment design, narration, or screen-by-screen treatment; and
- be something that could plausibly arrive through a future mass-ingestion process rather than only through manual curation of an existing course folder.

Reference material can still be useful without satisfying this test. It should simply be labeled separately and should not be used to claim that the system derived learning design from underlying factual material.

## Overall finding

The folder contains 46 files, including three operating-system metadata files. I did not find an unambiguous primary, authoritative source comparable to a statute, technical standard, official manual, research paper, or substantive SME-authored reference document. Most content-rich files belong to recognizable course-development packages. The remaining files are primarily glossaries, job aids, resource lists, scenario profiles, or correspondence.

Using these materials could demonstrate extraction or reconstruction of RLOs from existing instructional assets. It would not cleanly demonstrate the more difficult Phase 2 proposition of deriving candidate RLOs from factual source material that has not already been shaped for learning.

## Files that should clearly be excluded as primary source content

### US GAAP Fundamentals package

| File | Reason for exclusion |
|---|---|
| `ACC-LY24_ARS_US GAAP Fundamentals_Storyboard.docx` | Explicit storyboard containing slide titles, on-screen text, audio, navigation, acknowledgements, interactions, and course flow. This is a near-final instructional specification. |
| `ACC-LY24_ARS_US GAAP Fundamentals_RQ-FA-Document.docx` | Final-assessment document containing questions, answer options, correct answers, and feedback. It is also prominently marked restricted and confidential. It should not be ingested into a general-purpose source pipeline. |
| `ACC-LY24_ARS_US GAAP Fundamentals_Resources.docx` | A course resource sheet containing a link to DART, not the substantive source itself. The linked material might be evaluated separately if access and reuse rights permit. |

The package's glossary is addressed separately below because it contains factual definitions, but it is still a course-curated reference rather than a strong primary source.

### Federal Accounting Learning Program package

| File | Reason for exclusion |
|---|---|
| `FALP Module 1 eLearning (1).pptx` | Explicit e-learning design. It contains a course overview, portfolio-specific learning objectives, benefits, instructional sequence, knowledge checks, and course notes. |
| `17-05-24 GPS L&D Federal Bodies & Laws.pptx` | A 23-slide L&D presentation already selecting and organizing federal bodies, laws, and guidance into instructional sections. Slides refer to sources in their notes, but the underlying authoritative sources are not included as the primary inputs. |
| `Assessment Module 1.docx` | Assessment bank organized by stated objectives, with multiple formulations of questions and answer options. It encodes both the intended outcomes and assessment strategy. |

These files also overlap substantially. The decks and assessment form a coherent instructional package around federal regulatory bodies, laws, and guidance. Treating them as independent factual sources would allow course structure to leak directly into the generated RLOs.

### Blockchain package

| File or folder | Reason for exclusion |
|---|---|
| `Blockchain Module 1 - Blockchain Application .pptx` | Existing module design containing a learning objective, learning journey, topics, instructional definitions, application content, knowledge checks, and development comments comparing the outline with the finalized deck. |
| `Blockchain Client Conversation Savvy_LDS Queries.docx` | Learning-design discovery artifact. It records goals, desired behaviors, audience needs, content-outline questions, SME responses, and LDS recommendations. |
| `LDS-DTA- Project Intake Form.docx` | Course intake and project-management artifact describing business outcomes, performance outcomes, delivery needs, audience, urgency, and success measures. |
| `Video scripts/Topic 1 GOLD/` | Final or near-final narration scripts, transitions, durations, and knowledge checks. |
| `Video scripts/Topic 2 GOLD/` | Final or near-final instructional scripts organized around a predetermined sequence and learning purpose. |
| `Video scripts/Topic 3 GOLD/` | Scripted client examples and dialogue already shaped for instruction. |
| `Video scripts/Topic 4 GOLD/` | Scripted application guidance and course transitions. |

The video-script folders contain 21 Word documents. Their factual statements may be useful as secondary references, but their narration, sequencing, examples, and checks are already authored learning content. This is the clearest example of material that would make an RLO-generation test appear easier by supplying the desired instructional decisions in advance.

### Business Valuation 101 package

| File | Reason for exclusion |
|---|---|
| `BV101 LEARNING OBJECTIVES_gah.docx` | Explicit list of course learning objectives. |
| `BV101 Course Index.pdf` | Course-organization artifact rather than substantive domain source material. |
| `Business Valuation 101_Job Aid.pdf` | Existing performance-support output already curated and simplified for learners. |
| `FW BV101 Course Re-creation.msg` | Course-project correspondence, not domain source material. |
| `FW BV101 Next steps.msg` | Project correspondence, not domain source material. |

### Non-content files

The three `desktop.ini` files are operating-system metadata and should be ignored automatically by intake.

## Reference-only or provenance-dependent materials

These files should not be treated as clean primary-source examples, but they could have supporting roles if their provenance and intended use are clarified.

| File | Recommended treatment |
|---|---|
| `ACC-LY24_ARS_US GAAP Fundamentals_Glossary.docx` | Course-curated glossary. Useful for terminology normalization or validation, but definitions alone are generally too granular to drive meaningful RLO generation. |
| `Deloitte Business Glossary.pdf` | Reference vocabulary, not a curriculum source. Use for terminology or metadata enrichment rather than automatic RLO creation. |
| `Glossary_BV101 Terms.pdf` | Course-specific reference vocabulary. It may support another substantive source but should not independently generate an RLO for every term. |
| `Business Valuation 101 Resources Information.pdf` | Appears to identify course information resources. Treat it as a source locator; evaluate the underlying resources separately. |
| `Anderson Technology Overview.pdf` | Likely a course scenario or company profile. Confirm whether it describes a real authoritative case, an anonymized engagement, or a fictional instructional scenario before use. |
| `Newton Corporation Overview.pdf` | Likely scenario context created or selected for the BV101 course. Its provenance and factual status need confirmation. |
| `Speedy Engine Overview.pdf` | Likely scenario or system-context material. Confirm whether it is an independent technical reference or course-created support asset. |
| `Intercompany COE Training-1 (Intro-IC Framework).pptx` | Substantive and potentially SME-authored, but explicitly a 72-slide training deck with a course index, maturity model, framework sequence, leading practices, challenges, solutions, and case studies. It may be a useful secondary reference or a test of training-to-RLO conversion, but not a clean raw-source input. |

## Why this matters for a mass-ingestion demonstration

The issue is not that someone intentionally placed inappropriate files in a folder. The issue is that a course's `Source Content` folder is itself the result of human selection. It may mix:

- authoritative sources;
- SME summaries;
- instructional design artifacts;
- course outputs;
- assessment materials;
- scenario files;
- terminology references; and
- project correspondence.

A production-scale process would not safely assume that everything labeled `source` has the same evidentiary status. It would need an intake-classification stage that identifies these categories, prevents restricted assessments from entering the general corpus, and asks for provenance where the distinction is uncertain.

## Recommended request for replacement samples

For a clean Phase 2 test, request one or more materials that existed before and independently of the course, such as:

- an official law, regulation, standard, manual, or policy;
- a substantive technical or operating guide;
- an SME-authored paper or reference document with clear provenance;
- a public-domain government framework or guidance publication; or
- a bounded collection of authoritative materials that practitioners genuinely use to perform the work.

The associated intake form, objectives, storyboard, assessment, scripts, and completed course can be retained as a **comparison set**. They would be valuable for evaluating whether the RLOs derived from the true source material align with the decisions made by the original learning team, without allowing those decisions to leak into generation.
