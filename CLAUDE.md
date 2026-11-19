# Agent Brief — Automated E-Learning Prototyping

## What this repository is for

This repository explores how to generate runnable e-learning experiences from structured source content using modern web tooling.

The work here should be treated as product and platform exploration, not as a one-off slide exercise. The goal is to understand how to build a repeatable system that can turn course inputs into interactive learning outputs with minimal manual rework.

## Core objective

Given a content writeup, storyboard, transcript, or similar source material, produce a runnable lesson prototype that demonstrates how the material could be experienced by a learner.

The output does not need to mirror a legacy authoring tool. It should show how the content can be rendered clearly, interactively, and credibly within a generation pipeline that can evolve over time.

## What success looks like

The work should move toward a system that can:

1. Accept structured course content as input.
2. Render that content into interactive lesson outputs.
3. Support reusable templates, assets, and interaction patterns.
4. Remain compatible with enterprise delivery expectations where needed.
5. Preserve a clean separation between content, rendering, and packaging.

## Preferred mindset

Optimize for architecture and repeatability over imitation.

Good outputs are:

1. Runnable.
2. Faithful to the source content.
3. Clear in instructional structure.
4. Built from reusable patterns.
5. Easy to evolve into a broader generation system.

Avoid treating each course as a bespoke artifact unless the problem genuinely requires it.

## Design philosophy

### 1. Source-first

Source content should be the system of record. Generated files are outputs, not the canonical authored form.

### 2. Modular by default

Keep the following concerns separate wherever practical:

- content model
- templates and interaction patterns
- asset management
- rendering
- LMS or packaging concerns

### 3. Small vertical slices over broad mock completeness

When exploring feasibility, prefer a narrow end-to-end slice that actually runs over a wide prototype that hand-waves difficult parts.

### 4. Engineering quality matters early

Even when building a toy example, default toward an architecture that can grow: clear interfaces, deterministic generation paths, containerized dependencies where needed, and replaceable external services.

### 5. AI should assist, not destabilize

Model-driven steps can accelerate generation, refinement, or asset creation, but they should not be the only thing holding the system together. Structural validity and core behavior should remain deterministic.

## Output expectations

Generated lesson samples should aim to be:

1. Runnable with low setup friction.
2. Front-end first unless a backend is clearly justified.
3. Built on open-source tooling where possible.
4. Reasonably accessible.
5. Structured so narration, interactions, and assets can evolve into a fuller pipeline later.

## Delivery expectations

Assume that delivery may need to support both:

1. direct web playback for rapid prototyping and review
2. LMS-compatible packaging for enterprise environments

The repository should not assume that a prototype is complete unless the delivery path is understood.

## Accessibility baseline

Do not gold-plate accessibility, but do not treat it as optional.

At a minimum:

1. interactions should not be mouse-only
2. images should support alt text or equivalent description
3. structure should be understandable in semantic HTML terms
4. narration and transcript needs should be considered in the content model

## What to avoid

Avoid overfitting to any one course, tool export, or visual style.

In particular:

1. Do not assume a specific framework is the permanent answer.
2. Do not hard-code logic around one sample package unless it is being used intentionally as a temporary reference.
3. Do not optimize first for feature parity with legacy authoring tools.
4. Do not confuse generated build artifacts with maintainable source assets.

## Practical interpretation

When asked to create something in this repository, favor responses that strengthen the underlying platform direction:

1. define reusable patterns
2. keep source structures explicit
3. make interactions declarative where practical
4. keep rendering and packaging concerns cleanly separated
5. leave room for future additions such as richer media, scoring, narration, and LMS integration

## Final note

This repository is best understood as an exploration of automated e-learning generation as an engineering system.

The point is not just to make attractive slides. The point is to learn how to build a durable pipeline that can turn instructional source material into interactive, reviewable, and eventually deliverable learning experiences.