# HeyGen Captions and E-Learning Video Resolution Plan

Date: 2026-07-30
Branch: `feature/heygen-captions`

## Objective

Deliver switchable closed captions for HeyGen and Manim videos embedded in an
e-learning course, while ensuring that both renderers produce video matching the
course slide canvas of 1280×720.

The existing HeyGen v2 integration remains the preferred provider path. The API
version will not change unless a real v2 test proves that v2 cannot provide a
usable caption sidecar without permanently burning captions into the video.

## Constraints and decisions

- Preserve the provider-neutral `video.avatar.render` input and output contracts.
- Keep HeyGen generation on `POST /v2/video/generate` when technically viable.
- Store captions as a separate artifact; do not burn captions into the MP4.
- Convert provider caption formats to WebVTT before course packaging because the
  browser player consumes a `<track>` sidecar.
- Use 1280×720 as the canonical e-learning video size because it matches the
  Reveal slide canvas.
- Treat captions marked as required as required: missing or invalid captions
  must produce a clear failure rather than an apparently complete package.
- Use the same player behavior for HeyGen and Manim video insertions.

## Progress

### 1. Confirm HeyGen v2 behavior

- [x] Submit one minimal 1280×720 v2 avatar-video request with `caption: true`.
- [x] Confirm the completed status response field used for the caption URL.
- [x] Download the returned caption sidecar and identify its actual format.
- [x] Confirm the sidecar contains timed cues matching the spoken script.
- [x] Confirm whether the returned MP4 has captions permanently burned in.
- [x] Record the result below without storing credentials or expiring provider URLs.

Result:

> Completed 2026-07-30. `POST /v2/video/generate` accepted `caption: true`
> and `dimension: {width: 1280, height: 720}`. The completed v1 status
> response exposed the sidecar as `caption_url`. Its HTTP content type was
> generic `binary/octet-stream`, but content inspection confirmed a valid SRT
> file with three timed cues matching the submitted narration. The downloaded
> MP4 probed as exactly 1280×720. A frame captured at 2.0 seconds, during an
> active caption cue, contained no burned-in caption text. No credential,
> provider URL, provider operation ID, or generated media was added to the
> repository.

Decision: HeyGen v2 satisfies the switchable-caption requirement. Keep v2,
parse `caption_url`, store the SRT sidecar, and use the existing SRT-to-WebVTT
course assembly path.

Decision gate:

- If v2 returns SRT or VTT, use the existing conversion path.
- If v2 returns ASS/SSA, add deterministic conversion to WebVTT.
- If v2 returns no usable sidecar, or only a permanently captioned MP4, stop and
  document the limitation before considering a provider API-version change.

### 2. Correct the HeyGen caption boundary

- [x] Update the v2 status parser to recognize the response field proven by the
  smoke test, while retaining compatibility aliases such as `caption_url` and
  `subtitle_url` where appropriate.
- [x] Preserve the provider caption URL only long enough to download it; never
  expose the expiring URL as a workflow artifact.
- [x] Validate that requested caption bytes are non-empty, decodable, and contain
  timed cues before publishing them.
- [x] Store the raw caption sidecar under the workflow deliverables namespace with
  the correct filename and media type.
- [x] Return its logical artifact URI and media type through the existing avatar
  render output.
- [x] Fail clearly when `captions=true` but HeyGen returns no usable sidecar.

### 3. Standardize video dimensions

- [x] Define the e-learning media target as 1280×720 in the deterministic workflow
  builder rather than allowing the authoring model to choose it.
- [x] Change e-learning HeyGen jobs from 1920×1080 to 1280×720.
- [x] Keep e-learning Manim jobs on the `standard`/medium-quality profile, which
  renders at 1280×720.
- [x] Add output metadata or probing sufficient to verify the actual width and
  height returned by each renderer.
- [x] Fail with a specific media-validation error when an output is not 1280×720.
- [x] Add a defensive assembly check so mismatched video cannot silently enter a
  course package.

### 4. Normalize and package captions

- [x] Continue accepting Manim WebVTT/SRT captions through the existing path.
- [x] Convert HeyGen captions to valid WebVTT during bundle assembly.
- [x] Confirm ASS/SSA conversion is unnecessary because v2 returned valid SRT.
- [x] Stage the final caption file beside its video under `assets/` in the course
  package.
- [x] Include the caption file and media type in the package asset manifest.
- [x] Make a missing caption for a `captions_required` slot block assembly.

### 5. Add an explicit CC control

- [x] Add a visible CC button to the shared `video_player` component only when a
  caption track exists.
- [x] Toggle the associated `TextTrack.mode` between `showing` and `disabled`.
- [x] Keep captions on by default and synchronize the button's visible state.
- [x] Expose state using `aria-pressed`, an accessible label, and keyboard-native
  button behavior.
- [x] Ensure multiple video slides control only their own caption tracks.
- [x] Preserve native video controls as a fallback.

### 6. Automated verification

- [x] Add provider-client tests for the proven v2 request and response fields.
- [x] Add avatar-executor tests for successful caption persistence, missing
  required captions, invalid caption bytes, and artifact-write failure.
- [x] Add workflow-builder tests proving avatar dimensions are 1280×720 and caption
  outputs are wired into the assembler.
- [x] Add Manim tests proving the standard profile maps to 1280×720 output.
- [x] Add bundle tests for caption conversion, required-caption enforcement,
  dimension enforcement, and inclusion in the ZIP manifest.
- [x] Add player rendering and behavior tests for CC visibility, default state,
  toggling, accessibility attributes, and multiple video slides.
- [x] Run all focused caption, avatar, Manim, builder, and bundle tests.
- [x] Run the full repository test suite (`2043 passed, 14 skipped`).

### 7. End-to-end acceptance

- [ ] Generate one real e-learning package containing a HeyGen video.
- [ ] Verify the packaged video is exactly 1280×720.
- [ ] Verify captions are initially visible, can be turned off, and can be turned
  back on using the CC button.
- [ ] Verify the caption text is synchronized and is absent when CC is off.
- [ ] Generate or inspect one package containing a Manim video and repeat the same
  resolution and CC checks.
- [ ] Confirm no provider URLs, API keys, or temporary caption files appear in the
  downloadable package or committed files.

## Definition of done

The work is complete when both HeyGen and Manim e-learning videos are packaged at
1280×720 with valid WebVTT sidecars, the course player provides a working and
accessible CC on/off control, required-caption failures are explicit, and all
focused and repository tests pass.
