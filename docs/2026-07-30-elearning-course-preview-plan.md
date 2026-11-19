# E-Learning Course Preview Plan

Date: 2026-07-30
Branch: `feature/heygen-captions`

## Objective

Allow a business user to open a completed e-learning course directly from the
Generation Jobs tab. The course must run over HTTP so video captions, media
controls, and relative assets work without requiring the user to unzip and host
the package locally.

The existing ZIP download remains available and unchanged.

## Current state

- [x] Confirm completed e-learning jobs already expose the course ZIP through
  the commissioning API.
- [x] Confirm the ZIP contains `index.html`, course data, videos, and WebVTT
  caption files with correct relative paths.
- [x] Confirm the generated HTML links its video and caption assets correctly.
- [x] Confirm direct `file://` access is the remaining caption-loading problem.
- [x] Confirm the commissioning API can read the workflow artifact volume.
- [x] Confirm the Jobs tab already retrieves deliverables before rendering its
  completed-job actions.

## Scope decisions

- Add an **Open course** action only for completed e-learning jobs with a course
  ZIP.
- Open the course in a new tab; do not embed it inside the Generation Jobs page.
- Use the ZIP as the authoritative preview package so existing completed jobs
  can be previewed without regeneration.
- Extract the package lazily into an API-local temporary cache and serve its
  files with `FileResponse`. This preserves browser range requests for MP4
  playback and supplies correct MIME types for WebVTT captions.
- Do not add a separate web server, object-storage deployment, or package
  contract for this POC.
- Preserve the existing **Download course package** action.

## Implementation progress

### 1. Add a secure preview resolver

- [x] Resolve the completed job through the existing deliverables path.
- [x] Require a successful e-learning workflow and an available course ZIP.
- [x] Use the opaque, job-scoped deliverable identity rather than accepting an
  artifact URI from the browser.
- [x] Create one temporary preview directory per immutable completed package.
- [x] Validate every ZIP member before extraction: reject absolute paths,
  parent traversal, links, and entries outside the preview directory.
- [x] Make first-use extraction atomic so simultaneous preview requests cannot
  expose a partially extracted course.
- [x] Reuse the extracted directory for subsequent HTML, video, and caption
  requests during the API process lifetime.

Verification:

- [x] A valid completed course resolves to its extracted `index.html`.
- [x] A non-e-learning, incomplete, missing, or malformed package is rejected
  with a bounded, useful HTTP error.
- [x] Traversal and link-based ZIP fixtures cannot write outside the temporary
  preview directory.

### 2. Serve the course over HTTP

- [x] Add a trailing-slash preview entry route so relative `assets/...` URLs
  resolve beneath the job preview URL.
- [x] Add a job-scoped asset route for files inside the extracted package.
- [x] Resolve every requested path beneath the validated preview directory.
- [x] Return `index.html`, MP4, WebVTT, JSON, CSS, and JavaScript with correct
  media types; explicitly use `text/vtt` for caption files.
- [x] Use `FileResponse` so video requests support byte ranges and seeking.
- [x] Return 404 for missing package members without revealing filesystem or
  artifact-store paths.
- [x] Add conservative response headers appropriate for generated course
  content without blocking the existing inline player script.

Verification:

- [x] `index.html` loads through the commissioning API.
- [x] Every relative video and caption request returns 200 with the expected
  content type.
- [x] MP4 requests support browser byte-range behavior.
- [x] Unknown or out-of-root asset paths return 404.

### 3. Add the Generation Jobs action

- [x] When a completed e-learning job has a course ZIP, render **Open course**
  above **Download course package**.
- [x] Open the preview URL in a new tab with `noopener` protection.
- [x] Keep secondary files under the existing **Other files** disclosure.
- [x] Do not show the action for queued, running, failed, canceled, podcast, or
  video-only jobs.
- [x] Keep the completed table columns aligned when both actions are present.

Verification:

- [x] Browser test confirms a completed e-learning row shows both actions in
  the intended order.
- [x] Browser test confirms other job states and modalities do not show the
  preview action.
- [x] Existing restart, cancel, download, and polling behavior is unchanged.

### 4. End-to-end acceptance

- [x] Rebuild and restart the commissioning API.
- [x] Open the current ADKAR course from the Generation Jobs tab.
- [ ] Confirm navigation, interactions, and progress behavior still work.
- [ ] Confirm HeyGen video playback and CC on/off behavior.
- [ ] Confirm Manim video playback and CC on/off behavior.
- [ ] Confirm captions appear without any local unzip or hosting instructions.
- [x] Confirm the original ZIP still downloads and opens normally when hosted.
- [x] Run focused API and browser tests (`15 passed`; the isolated browser
  fixture skipped because the live API occupied its fixed port, then the live
  Jobs page and ADKAR preview were verified in headless Chrome).
- [x] Run the full repository test suite (`2062 passed, 14 skipped`).

## Failure semantics

- Preview preparation must never modify the authoritative ZIP or workflow
  artifacts.
- A preview failure must not change the completed job state or remove its
  download action.
- Invalid ZIP content fails closed; the API does not partially serve it.
- A missing preview cache is reconstructed from the completed ZIP on demand.
- API restarts may clear the temporary preview cache without affecting jobs or
  deliverables.

## Definition of done

A completed e-learning job offers **Open course** and **Download course
package** actions. **Open course** launches the generated module in a new tab
over HTTP, all relative assets load from a job-scoped route, both HeyGen and
Manim captions display and toggle correctly, and no business user must run a
local server.
