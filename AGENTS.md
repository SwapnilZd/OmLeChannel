# Repository Agent Guidance

## Working approach

These rules apply to automated coding work throughout the repository. For trivial changes, use proportionate judgment.

### Think before coding

- Confirm assumptions from the repository before implementing.
- Surface materially different interpretations and tradeoffs; do not choose silently when the decision affects behavior or architecture.
- Prefer a simpler approach when it meets the requirement.
- If required information is unavailable or contradictory, state the exact uncertainty before proceeding.

### Keep solutions simple

- Implement only the requested behavior.
- Avoid abstractions, configurability, fallback paths, and defensive handling without a demonstrated need.
- Rewrite an overcomplicated implementation before considering it complete.

### Make surgical changes

- Touch only code needed for the requested behavior.
- Match established repository patterns and style instead of introducing a competing convention.
- Do not refactor, reformat, or remove unrelated code.
- Remove imports, variables, functions, and files made obsolete by the current change.
- Mention unrelated problems rather than changing them without scope.

### Work toward observable goals

- Define success in terms of behavior that can be exercised.
- For a bug, reproduce it before fixing it and confirm the reproduction no longer fails.
- For a refactor, verify relevant behavior before and after.
- For multi-step work, maintain a short plan whose steps include their verification.
- Continue until the requested behavior is implemented and verified.

## Project direction

- Treat this repository as a repeatable e-learning generation platform, not a collection of bespoke slide artifacts.
- Keep source content canonical; generated files are outputs.
- Preserve separation between content models, templates and interactions, assets, rendering, and packaging.
- Prefer narrow, runnable vertical slices over broad mock implementations.
- Keep core structure and validity deterministic even when model-driven steps assist generation.
- Support direct web review while keeping enterprise and LMS delivery paths explicit.
- Do not overfit logic to one course, sample package, framework, authoring tool, or visual style.

## Accessibility baseline

- Interactions must not be mouse-only.
- Images need alt text or an equivalent description.
- Use semantic structure that remains understandable without styling.
- Account for narration and transcript requirements in content models where relevant.

## Runtime and testing

- Run builds, tests, and application smoke checks in containers. Do not create or use local virtual environments.
- Verify UI changes against the running containerized application.

## LiteLLM configuration

All model-backed pipeline tools share:

```text
LITE_LLM_BASE_URL=http://litellm:4000
LITE_LLM_API_KEY=<master key>
```

Do not add tool-specific endpoint, credential, or model-selection environment variables. Add purpose-specific aliases to `litellm/config.yaml` and reference those aliases from application code. Provider model IDs belong only in `litellm/config.yaml`.
