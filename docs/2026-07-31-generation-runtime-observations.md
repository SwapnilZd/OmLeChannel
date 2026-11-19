# Generation Runtime Observations and Punch List

This document records operational findings from end-to-end generation jobs. It
is intended to separate observed behavior from proposed changes so performance
work can be prioritized using evidence from real runs.

## Job: `assembly-5e06e5c4c9cc4703b8ab61d3`

Status: succeeded on July 31, 2026.

Total workflow time: approximately 8 minutes 49 seconds.

### Stage observations

- Course authoring succeeded on its first attempt in 27.56 seconds. Its two
  draft batches ran concurrently, followed by a semantic review with no
  findings.
- `complete-smart-goal-build` failed its first Manim pre-render geometry check.
  The repair call and preparation for the second attempt took approximately 87
  seconds. The second render succeeded. Total task time was 310.75 seconds and
  the produced video was approximately 168 seconds long.
- Parallel narration prefetch worked for `complete-smart-goal-build`, detecting
  and generating nine speech segments before the animation render.
- `smart-framework-build` succeeded on its first render attempt, but its source
  placed a dynamic `text` value inside one repeated voiceover block. The static
  prefetcher could not identify those runtime values, so speech remained in the
  inline render path. Total task time was 361.55 seconds and the produced video
  was approximately 149 seconds long.
- HeyGen was the critical path. The welcome-avatar task succeeded on its first
  attempt in 528.18 seconds.
- Final bundle assembly succeeded in 0.50 seconds.
- The course preview served the HeyGen and Manim MP4/VTT assets successfully.
- After workflow completion, `workflow_runs.status` was `succeeded`, but the raw
  `commissioning_jobs.state` remained `queued_for_execution`. The API still
  served the preview, deliverables, and cost endpoints successfully. This is a
  persistence/status-synchronization inconsistency even if the UI derives the
  effective state elsewhere.

### Punch list

- [x] Route Manim repair calls through a dedicated `manim-scene-repair` LiteLLM
  alias configured with low reasoning effort.
- [x] Guide embedded e-learning avatar segments toward brief 20–45 second
  introductions and transitions, without constraining standalone video outputs.
- [x] Support safe prefetching for generated narration expressed as static
  iterable data consumed by a dynamic voiceover loop.
- [x] Make the prefetch log distinguish "no statically recognizable plan" from
  "all recognized narration was already cached."
- [ ] Reduce geometry-repair frequency by giving scene generation clearer
  template/layout constraints before the first render.
- [ ] Reconcile the persisted commissioning job state with terminal workflow
  state so completed jobs never remain `queued_for_execution` in storage.
- [ ] Add more visible per-stage progress to the Jobs UI, especially HeyGen
  polling, Manim drafting, speech prefetch, rendering, repair, and FFmpeg
  post-processing.
