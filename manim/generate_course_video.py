#!/usr/bin/env python3
"""
E-Learning Video Generator

Pipeline:
  1. GPT-5.5 plans scenes from input script (narration per element, no quiz/tooltips)
  2. GPT-5.5 writes a Manim VoiceoverScene per scene (animations synced to TTS narration)
  3. Manim renders each scene → MP4 with TTS audio routed through LiteLLM
  4. ffmpeg concatenates scene MP4s → final course_video.mp4

Usage:
    python generate_course_video.py
    python generate_course_video.py --script input/eho_script.txt --output video_output/
    python generate_course_video.py --no-render          # code generation only
    python generate_course_video.py --voice onyx         # change narrator voice
    python generate_course_video.py --controller         # delegate to canonical ManimGenerationController

Requires: LITE_LLM_BASE_URL and LITE_LLM_API_KEY environment variables
Install:  pip install "manim-voiceover[openai]"

--controller mode
-----------------
When --controller is given, the script delegates to the canonical
ManimGenerationController from learning_pipeline.tools.manim_video.
It requires LITE_LLM_BASE_URL and LITE_LLM_API_KEY (shared with all other
pipeline tools), and expects the pipeline package to be importable (i.e.
run from the repo root or inside the learning-pipeline container).

All existing presentation flags (--script, --output, --voice, --quality,
--no-render) are still accepted in legacy mode.
"""

import os
import sys
import re
import json
import hashlib
import subprocess
import argparse
import textwrap
from pathlib import Path
from templates import REGISTRY, TEMPLATE_SYSTEM
from llm_gateway import (
    ModelAlias,
    build_langfuse_headers,
    build_litellm_metadata,
    load_lite_llm_settings,
)

# Client is created lazily so --render mode can start without model credentials.
_client = None

def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        connection = load_lite_llm_settings()
        _client = OpenAI(
            base_url=connection.base_url,
            api_key=connection.api_key,
        )
    return _client

_DEFAULT_MODEL = ModelAlias.LEGACY_COURSE_VIDEO_GENERATION

_TTS_IMPORT = 'from tts_service import LiteLLMTTSService'
_TTS_SERVICE_CALL = (
    f'LiteLLMTTSService(voice="{{voice}}", model="{ModelAlias.MANIM_SPEECH_SYNTHESIS}", '
    'transcription_model=None)'
)
_DEFAULT_VOICE = 'Kore'

# ── LiteLLM helpers ───────────────────────────────────────────────────────────

def chat(system: str, user: str, model: str, json_mode: bool = False) -> str:
    kwargs = {
        "model": model,
        "extra_body": {
            "metadata": build_litellm_metadata(
                model,
                operation="legacy-course-video",
                job_id=os.environ.get("LLM_TELEMETRY_JOB_ID"),
            )
        },
        "extra_headers": build_langfuse_headers(
            model,
            operation="legacy-course-video",
            job_id=os.environ.get("LLM_TELEMETRY_JOB_ID"),
        ),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "reasoning_effort": "high",
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _get_client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


def chat_json(system: str, user: str, model: str) -> dict:
    return json.loads(chat(system, user, model, json_mode=True))

# ── Step 1: Scene planner ──────────────────────────────────────────────────────

PLANNER_SYSTEM = textwrap.dedent("""\
    You are a learning experience designer. Convert transcripts into structured
    narrated video e-learning courses. Return ONLY valid JSON.
""")

PLANNER_PROMPT = textwrap.dedent("""\
    Analyse this course content and plan a multi-scene narrated e-learning video course.
    Each scene becomes a self-contained animated video segment with spoken narration.
    Decide scene count based on content — aim for 3–7 scenes; never force content
    into fewer scenes than the material warrants.

    Return a JSON object with this exact structure:

    {{
      "course_title": "string",
      "course_description": "1-2 sentence overview",
      "scenes": [
        {{
          "id": "snake_case_id",
          "title": "Scene Title",
          "visual_type": "chess_board | myth_vs_reality | scenario | vertical_stack | central_callouts | two_column | free_form",
          "scene_narration": "Spoken intro for this scene. 1-2 sentences introducing the concept.",
          "elements": [
            {{
              "id": "snake_case_element_id",
              "label": "Short Display Label (3-5 words)",
              "narration": "What the narrator says as this element animates onto screen. 1-2 sentences grounded in the transcript."
            }}
          ],
          "closing_narration": "Spoken wrap-up. 1-2 sentences that close the scene."
        }}
      ]
    }}

    === VISUAL TYPE GUIDE ===

    chess_board      Use when content describes a specific board position, legal move rules,
                     captures, or blocking scenarios. 3-6 elements: first element is the
                     initial position setup; remaining elements are moves, highlights, or
                     indicators animated in sequence.

    myth_vs_reality  Use when content corrects common misconceptions. Elements MUST be even
                     (min 4, max 8): odd-indexed = misconception, even-indexed = correction.

    scenario         Use when content presents a concrete situation with a correct answer.
                     Exactly 4 elements: [0] setup, [1] question, [2] wrong (label "✗ ..."),
                     [3] correct (label "✓ ...").

    vertical_stack   Use when listing 3-4 distinct items, steps, principles, or rules.
                     Each card reveals in sequence with narration. Best for enumerated
                     content where items stand alone and don't need comparison.
                     3-4 elements, one per card.

    central_callouts Use when showing a core concept with 3-8 surrounding properties,
                     related terms, or supporting points. A hub circle with labelled arrows
                     radiates outward. Good for definitions with attributes, or a topic
                     3-8 elements, one per callout.

    two_column       Use when comparing or contrasting two categories side by side.
                     Paired rows appear one at a time. Best for "X vs Y", "before/after",
                     "legal vs illegal", or similar binary groupings. 2-6 element pairs.

    free_form        Use for everything else. The Manim code generator will design the
                     visual layout freely based on the content. Elements describe what
                     should be communicated, not how to render it. 3-6 elements.

    === RULES ===
    - Prefer chess_board, myth_vs_reality, or scenario when the content clearly fits.
      Use vertical_stack for plain lists; central_callouts for hub-and-spoke concepts;
      two_column for side-by-side comparisons. Use free_form when none are a natural match.
    - Default element count: 3-6. myth_vs_reality requires an even count (max 6);
      scenario requires exactly 4.
    - Element ids must be unique across the entire course, not just within a scene.
    - Do not repeat visual types back-to-back if avoidable.
    - Ground all narration in direct quotes or close paraphrases from the transcript.
    - Each element narration: 1-2 sentences (~15-25 words). It will be spoken aloud as the
      element appears, so it must match the visual label naturally.
    - scene_narration and closing_narration: 1-2 sentences each.

    Transcript:
    {script}
""")


def _rlo_objectives_lines(rlo: dict) -> list[str]:
    lines: list[str] = []
    if obj := rlo.get('terminal_objective'):
        lines.append(f"\nTERMINAL OBJECTIVE:\n{obj}")
    if ctx := rlo.get('performance_context'):
        lines.append(f"\nPERFORMANCE CONTEXT:\n{ctx}")
    if los := rlo.get('learning_objectives', []):
        lines.append("\nLEARNING OBJECTIVES:")
        for lo in los:
            lines.append(f"  [{lo.get('bloom_level', '').upper()}] {lo.get('statement', '')}")
    return lines


def _rlo_concept_lines(c: dict) -> list[str]:
    lines = [f"\n  {c.get('name', '')}:", f"    Definition: {c.get('definition', '')}"]
    if elab := c.get('elaboration'):
        lines.append(f"    Detail: {elab}")
    for m in c.get('misconceptions', []):
        lines.append(f"    Misconception: {m.get('misconception', '')}")
        lines.append(f"    Correction: {m.get('correction', '')}")
    return lines


def _rlo_case_lines(case: dict) -> list[str]:
    lines = [f"\n  Scenario — {case.get('title', '')}:"]
    for key, label in [('setup', 'Setup'), ('decision_point', 'Question'), ('correct_action', 'Correct answer')]:
        if val := case.get(key):
            lines.append(f"    {label}: {val}")
    return lines


def load_input(path: Path) -> str:
    """Read the input file and return text suitable for the scene planner.

    .json files are treated as RLO documents: their structured fields
    (objectives, concepts, cases) are formatted into a readable brief.
    All other files are returned as plain text.
    """
    if path.suffix.lower() != '.json':
        return path.read_text()

    rlo = json.loads(path.read_text())
    lines: list[str] = []

    for key, label in [('topic', 'TOPIC'), ('domain', 'DOMAIN'), ('level', 'LEVEL')]:
        if val := rlo.get(key):
            lines.append(f"{label}: {val}")

    lines.extend(_rlo_objectives_lines(rlo))

    if concepts := rlo.get('concepts', []):
        lines.append("\nCONCEPTS:")
        for c in concepts:
            lines.extend(_rlo_concept_lines(c))

    if cases := rlo.get('cases', []):
        lines.append("\nPRACTICAL SCENARIOS:")
        for case in cases:
            lines.extend(_rlo_case_lines(case))

    return "\n".join(lines)


def plan_scenes(script: str, model: str) -> dict:
    print("  Planning scenes...")
    return chat_json(PLANNER_SYSTEM, PLANNER_PROMPT.format(script=script), model)

# ── Step 2a: Manim code generator ─────────────────────────────────────────────

MANIM_SYSTEM = textwrap.dedent("""\
    You are a Manim animation expert writing narrated e-learning video scenes.
    Use manim-voiceover with LiteLLM TTS to sync animations to speech.
    Return ONLY valid JSON with a single key "manim_code".
""")

MANIM_PROMPT = textwrap.dedent("""\
    Write a complete Manim Python file for this narrated learning scene.
    Return JSON: {{"manim_code": "..."}}

    === SCENE ===
    ID:           {scene_id}
    Title:        {title}
    Visual type:  {visual_type}

    === NARRATION SCRIPT ===
    Opener:  {scene_narration}
    Elements (narrated in this order as each animates in):
    {elements_list}
    Closer:  {closing_narration}

    === CODE SKELETON ===

    from manim import *
    from manim_voiceover import VoiceoverScene
    {tts_import}

    # ── Deloitte Primary Palette ─────────────────────────────────────────
    DELOITTE_GREEN      = "#86BC25"   # primary brand green — headlines, key accents
    MID_GREEN           = "#26890D"
    DEEP_GREEN          = "#046A38"
    DARK_GREEN          = "#1C3D26"
    DELOITTE_DARK_GRAY  = "#222222"   # slide background
    DELOITTE_LIGHT_GRAY = "#E6E6E6"
    DELOITTE_WHITE      = "#FFFFFF"

    # ── Deloitte Secondary Palette — charts, graphs, data series, variety ─
    GREEN_2  = "#C4D600";  GREEN_4 = "#43B02A";  GREEN_5 = "#009A44"
    TEAL_3   = "#6FC2B4";  TEAL_4  = "#00ABAB";  TEAL_6  = "#007680"
    BLUE_2   = "#62B5E5";  BLUE_3  = "#00A3E0";  BLUE_4  = "#0076A8"
    COOL_GRAY_7 = "#97999B";  COOL_GRAY_9 = "#75787B"
    CARD_BG     = "#2A2A2A"   # card/panel fill — slightly lighter than background

    config.background_color = DELOITTE_DARK_GRAY
    FONT = "Open Sans"

    class Scene_{scene_id}(VoiceoverScene):
        def construct(self):
            self.set_speech_service({tts_service_call})

            # ── Opener ──────────────────────────────────────────────────────
            with self.voiceover(text="{scene_narration}") as tracker:
                self.wait(tracker.duration)

            # ── Build visual + narrate each element ─────────────────────────
            # (follow the layout rules below; for free_form design freely)

            # ── Closer ──────────────────────────────────────────────────────
            with self.voiceover(text="{closing_narration}") as tracker:
                self.wait(tracker.duration)

    === LAYOUT RULES ===

    FREE_FORM
      Design the scene layout to match the content — do not force it into a rigid template.
      The following rules apply to ALL scenes (including free_form) and must be respected.

      SAFE ZONE — never place any object outside this region:
        X ∈ [-6.5, 6.5],  Y ∈ [-3.8, 3.8]
        A title at y=3.4 with font_size=30 has its top edge at ~3.7 — just inside safe zone.
        Any Text or shape whose bounding box top exceeds 3.8 will clip. Check before placing.

      TEXT SIZING — fixed scale, never deviate:
        Title / scene header:   font_size=28-32,  placed at y ≥ 3.0
        Section label:          font_size=22-26
        Body / card text:       font_size=18-22
        Annotation / callout:   font_size=14-18
        Caption / axis label:   font_size=11-14
        Never exceed font_size=34. Short labels only — keep label strings under 30 chars.

      TEXT OVERFLOW — always set width= on any Text that is not a short single-word label:
        Full-width body text:   width=12
        Side-panel or column:   width=5.5
        Card / box interior:    width=9
        Text without width= that is longer than ~20 chars will silently overflow the frame.

      POSITIONING — prefer relative over absolute:
        Good:   label.next_to(box, DOWN, buff=0.25)
        Good:   group = VGroup(a, b, c); group.arrange(DOWN, buff=0.3); group.move_to(ORIGIN)
        Avoid:  label.move_to(np.array([0, -2.3, 0]))  # only acceptable for the anchor object
        Minimum buffer between any two objects' bounding boxes: 0.2 units.
        Use buff= consistently — never rely on default buff=0 (objects will touch).

      Z-INDEX — always set on overlapping objects:
        Background shapes:  z_index=0
        Main content:       z_index=5
        Annotations/arrows: z_index=8
        Title:              z_index=12
        VGroup z_index applies to all children.

      COMPOSITIONAL APPROACHES — choose what fits the content:

        Central focus + callouts:
          One anchor shape (circle, rect, or icon) at or near center/left-of-center.
          Arrows + Text callouts radiate outward, one per voiceover block.
          Keep anchor at |x| ≤ 1.5; callouts at radius ≥ 2.5 from anchor center.
          Use Arrow(start, end, buff=0.2) so arrow tips don't overlap the shapes.

        Vertical card stack (3-5 items):
          cards = VGroup(*[make_card(label) for label in labels])
          cards.arrange(DOWN, buff=0.3)
          cards.move_to(ORIGIN)  # or shift left/right if title occupies top
          Each card fades/slides in during its voiceover block.
          Max 5 cards. Card height ≤ 0.9 units. Total stack height must fit Y ∈ [-3.2, 2.6].

        Two-column split:
          Left column anchor x=-3.5, right column anchor x=3.5.
          DashedLine(UP*3.5, DOWN*3.5, color=COOL_GRAY_9) divider at x=0.
          Column headers at y=3.0. Items stack downward from y=2.2, step 0.9.
          Max 4 items per column.

        Progressive build (concept map / network):
          First node at ORIGIN or slightly left. Each subsequent node placed with
          next_to() or at a computed angle. Connect with Line or Arrow.
          Radius of spoke nodes from center: 2.5-3.0. Label placed beyond node
          using node_pos + normalize(node_pos) * 0.4, font_size=16-18.

        Annotated diagram:
          Large central shape or icon. Step-by-step annotations (Arrow + label) appear
          around it, each in its own voiceover block. Arrows should point INTO the
          relevant part of the shape with buff=0.15 so they touch cleanly.

    === TIMING RULES ===
    - Every voiceover context block MUST contain at least one self.play() or self.wait().
    - Use run_time=tracker.duration to sync animation length to speech duration.
    - Guard against very short audio: run_time=max(0.8, tracker.duration)
    - Never call self.wait() outside a voiceover block — it adds unwanted silence.
    - Build all mobjects BEFORE opening the voiceover context for that element.

    === THEMING RULES ===
    Primary palette (DELOITTE_GREEN, MID_GREEN, DEEP_GREEN, DARK_GREEN,
    DELOITTE_DARK_GRAY, DELOITTE_LIGHT_GRAY, DELOITTE_WHITE):
    - Use for slide backgrounds, scene titles, headlines, and primary call-outs.
    - DELOITTE_GREEN is the main accent color — use it to draw the eye to the key idea.
    - Body text and labels should use DELOITTE_WHITE or DELOITTE_LIGHT_GRAY on dark backgrounds.
    - Borders and dividers should use COOL_GRAY_9 or COOL_GRAY_7.

    Secondary palette (GREEN_2/4/5, TEAL_3/4/6, BLUE_2/3/4, COOL_GRAY_7/9):
    - Use exclusively for data series, charts, graphs, and multi-item visual variety.
    - Prefer teals and blues to differentiate series; greens to reinforce brand emphasis.
    - Never use the secondary palette for slide backgrounds or primary text.
    - Cycle order for sequential data series: BLUE_3 → TEAL_4 → GREEN_4 → BLUE_4 → TEAL_6 → GREEN_5.

    General:
    - Background is always DELOITTE_DARK_GRAY (#222222).
    - Never use arbitrary hex strings — every color must reference a named constant above.
    - Do not invent colors outside the palette. If you need a subtle fill, use CARD_BG.

    === IMPORT & QUALITY NOTES ===
    - CRITICAL: Copy the {tts_import} line and self.set_speech_service({tts_service_call}) line
      EXACTLY as shown in the skeleton — do not substitute a different service, voice, or model.
    - import numpy as np  (needed for network_diagram angle math)
    - Use font=FONT on every Text() call — never omit it or use a different font string.
    - Do NOT include ELearningScene, _export_all, or self.elements — video only.
    - Do NOT add a progress bar, quiz, or interactive overlay.
    - Keep all text short enough to fit on screen (font_size already sized per type above).
""")


def _enforce_tts(code: str, tts_import: str, service_call: str) -> str:
    """Overwrite whatever TTS import/service the LLM generated with the correct ones.

    LLMs occasionally substitute a familiar service (e.g. OpenAIService) even when
    the prompt specifies a different one. This ensures the pipeline's chosen service
    is always used, regardless of model compliance.
    """
    # Replace any manim_voiceover service import line
    code = re.sub(
        r'from manim_voiceover\.services\.\w+ import \w+',
        tts_import,
        code,
    )
    # Replace set_speech_service(...) — handles one level of nested parens
    code = re.sub(
        r'self\.set_speech_service\([^()]*(?:\([^()]*\))*[^()]*\)',
        f'self.set_speech_service({service_call})',
        code,
    )
    return code


def generate_manim_code(scene: dict, model: str, voice: str) -> str:
    service_call = _TTS_SERVICE_CALL.format(voice=voice)

    template = REGISTRY.get(scene.get('visual_type', ''))
    if template is not None:
        try:
            raw = chat_json(TEMPLATE_SYSTEM, template.fill_prompt(scene), model)
            code = template.render(template.validate(raw), scene['id'], cfg['import'], service_call)
            return _enforce_tts(code, cfg['import'], service_call)
        except Exception as exc:
            print(f"    ⚠ Template '{scene['visual_type']}' failed ({exc}), falling back to free-form")

    elements_list = "\n".join(
        f"  [{i+1}] id='{e['id']}', label='{e['label']}'\n"
        f"       narration: \"{e['narration']}\""
        for i, e in enumerate(scene['elements'])
    )
    result = chat_json(
        MANIM_SYSTEM,
        MANIM_PROMPT.format(
            scene_id=scene['id'],
            title=scene['title'],
            visual_type=scene['visual_type'],
            scene_narration=scene['scene_narration'],
            elements_list=elements_list,
            closing_narration=scene['closing_narration'],
            tts_import=_TTS_IMPORT,
            tts_service_call=service_call,
        ),
        model,
    )
    return _enforce_tts(result['manim_code'], cfg['import'], service_call)

# ── Step 2b: Run Manim ─────────────────────────────────────────────────────────

def run_manim_scene(manim_path: Path, scene_id: str, quality: str = "h") -> Path | None:
    """Render a scene. Returns the absolute path to the output MP4, or None on failure."""
    cwd = manim_path.parent

    cmd = [sys.executable, "-m", "manim", f"-q{quality}", manim_path.name, f"Scene_{scene_id}"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(cwd), timeout=300
        )
    except subprocess.TimeoutExpired as exc:
        print("    ✗ Manim timed out after 5 minutes")
        partial = exc.stderr or ''
        if partial.strip():
            tail = "\n      ".join(partial.strip().splitlines()[-20:])
            print(f"    Last output before timeout:\n      {tail}")
        return None

    if result.returncode != 0:
        stderr_tail = "\n      ".join(result.stderr.strip().splitlines()[-10:])
        print(f"    ✗ Manim render failed:\n      {stderr_tail}")
        return None

    # Locate this scene's MP4. Filter by stem == class name so we never
    # pick up a sibling scene's file from the shared media/videos/ tree.
    class_name = f"Scene_{scene_id}"
    video_root = cwd / 'media' / 'videos'
    if video_root.exists():
        matches = [
            p for p in video_root.rglob('*.mp4')
            if 'partial_movie_files' not in str(p) and p.stem == class_name
        ]
        if matches:
            return matches[0].resolve()

    print(f"    ✗ No MP4 found for {class_name} after render")
    return None

# ── Step 3: Concatenate videos ────────────────────────────────────────────────

def concatenate_videos(video_paths: list[Path], output_path: Path) -> bool:
    """Concatenate MP4s using ffmpeg stream-copy (no re-encode)."""
    if not video_paths:
        print("  No videos to concatenate.")
        return False

    list_file = output_path.parent / '_concat_list.txt'
    list_file.write_text('\n'.join(f"file '{p}'" for p in video_paths))

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', str(list_file),
        '-c', 'copy',
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"  ✗ ffmpeg concat failed:\n    {result.stderr.strip()[-600:]}")
        return False

    return True

# ── Per-scene pipeline ─────────────────────────────────────────────────────────

def process_scene(
    scene: dict, num: int, total: int,
    scenes_dir: Path, model: str, voice: str, render: bool,
    quality: str = "h"
) -> Path | None:
    sid = scene['id']
    print(f"\n  [{num}/{total}] {scene['title']}  [{scene['visual_type']}]")

    # 2a — Generate Manim code
    print("    Generating Manim code...")
    manim_path = scenes_dir / f'scene_{num:02d}_{sid}.py'
    manim_path.write_text(generate_manim_code(scene, model, voice))
    print(f"    → {manim_path.name}")

    if not render:
        return None

    # 2b — Render
    print("    Rendering (Manim + LiteLLM TTS)...")
    video_path = run_manim_scene(manim_path, sid, quality)
    if video_path:
        print(f"    → {video_path.name}")
    return video_path

# ── Finalise video ─────────────────────────────────────────────────────────────

def _finish_video(video_paths: list[Path], out: Path, scenes_dir: Path) -> None:
    print(f"\nStep 3/3 — Concatenating {len(video_paths)} scene videos...")
    if not video_paths:
        print("  No scene videos were produced — check render errors above.")
        return
    final_path = out / 'course_video.mp4'
    if concatenate_videos(video_paths, final_path):
        size_mb = final_path.stat().st_size / 1_048_576
        print(f"  course_video.mp4  ({size_mb:.1f} MB) ✓")
        print(f"\n{'─'*55}")
        print("  Course video ready!")
        print(f"  {final_path.resolve()}")
        print('─'*55)
    else:
        print(f"  Concatenation failed — individual scene videos in: {scenes_dir}")


# ── Render mode (called by ContainerManimRenderRunner) ────────────────────────


# Approved Deloitte tagline outro (brand/outro/, baked into the image).
# Usage table: "Video outros and end frames: Yes". Disable per run with
# MANIM_BRAND_OUTRO=off for content the tagline must not carry (e.g. A&A, T&L).
_OUTRO_PATH = Path("/app/brand/outro.mp4")
_OUTRO_FADE_SECONDS = 0.5


def _append_brand_outro(video_path: Path) -> str | None:
    """Concatenate the approved tagline outro onto *video_path* in place.

    Fades the main video to black over the final half second, scales the outro
    to the rendered resolution/frame rate, and pairs it with a silent audio
    track so the streams concat cleanly. Returns an error message on failure,
    None on success.
    """
    if not _OUTRO_PATH.exists():
        return (
            f"Brand outro asset missing at {_OUTRO_PATH} "
            "(rebuild the renderer image, or set MANIM_BRAND_OUTRO=off)."
        )

    def _probe(path: Path, *args: str) -> str:
        result = subprocess.run(
            ["ffprobe", "-v", "error", *args, "-of", "csv=p=0", str(path)],
            capture_output=True, text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    video_line = _probe(
        video_path, "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
    )
    audio_line = _probe(
        video_path, "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels",
    )
    duration_line = _probe(video_path, "-show_entries", "format=duration")
    outro_duration = _probe(_OUTRO_PATH, "-show_entries", "format=duration")
    if not (video_line and audio_line and duration_line and outro_duration):
        return "Could not probe rendered video/outro for the outro concat."

    width, height, frame_rate = video_line.split(",")[:3]
    sample_rate, channels = audio_line.split(",")[:2]
    fade_start = max(0.0, float(duration_line) - _OUTRO_FADE_SECONDS)
    channel_layout = "mono" if channels.strip() == "1" else "stereo"

    spliced = video_path.with_name("video-with-outro.mp4")
    filter_complex = (
        f"[0:v]fade=t=out:st={fade_start:.3f}:d={_OUTRO_FADE_SECONDS}[v0];"
        f"[1:v]scale={width}:{height},fps={frame_rate}[v1];"
        f"[v0][0:a][v1][2:a]concat=n=2:v=1:a=1[v][a]"
    )
    concat = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(_OUTRO_PATH),
            "-f", "lavfi", "-t", outro_duration,
            "-i", f"anullsrc=channel_layout={channel_layout}:sample_rate={sample_rate}",
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            str(spliced),
        ],
        capture_output=True, text=True,
    )
    if concat.returncode != 0 or not spliced.exists():
        tail = (concat.stderr or "").strip()[-2000:]
        return f"Outro concat failed (ffmpeg code {concat.returncode}).\n{tail}"
    spliced.replace(video_path)
    return None


def _run_render_mode() -> None:
    """Execute pre-generated scene.py from /app/input and write artifacts to /app/output.

    Called when the container is launched with --render by ContainerManimRenderRunner.
    No scene-generation LLM call is made. Manim runs the supplied source;
    VoiceoverScene performs synchronized TTS through its injected speech-service
    adapter and writes the resulting audio into the rendered MP4.

    Input contract  (/app/input):
        scene.py       — Manim Python source generated by the controller
        request.json   — {"job_id", "scene_class", "quality", "expected_duration_seconds"}

    Output contract (/app/output):
        result.json    — {"status": "success"|"failure", ...}
        video.mp4      — rendered video (TTS audio embedded by VoiceoverScene inline)
        render.log     — combined stdout+stderr from Manim
    """
    import shutil
    import tempfile

    input_dir = Path("/app/input")
    output_dir = Path("/app/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    def _write_result(data: dict) -> None:
        (output_dir / "result.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def _failure_excerpt(log: str, limit: int = 4000) -> str:
        value = log.strip()
        return value[-limit:] if value else "No Manim diagnostic output was captured."

    scene_py = input_dir / "scene.py"
    if not scene_py.exists():
        _write_result({
            "status": "failure",
            "failure_category": "infrastructure_error",
            "failure_message": "scene.py not found in /app/input",
        })
        sys.exit(1)

    manifest: dict = {}
    request_json = input_dir / "request.json"
    if request_json.exists():
        try:
            manifest = json.loads(request_json.read_text(encoding="utf-8"))
        except Exception as exc:
            _write_result({
                "status": "failure",
                "failure_category": "infrastructure_error",
                "failure_message": f"Could not parse request.json: {exc}",
            })
            sys.exit(1)

    scene_class = manifest.get("scene_class", "Scene")
    quality = manifest.get("quality", "high")
    expected_duration = manifest.get("expected_duration_seconds")

    # ── Geometry gate ──────────────────────────────────────────────────────────
    # Measure real text geometry BEFORE spending render/TTS time. Violations are
    # a repairable source defect: the controller routes any non-infrastructure
    # failure_category into its bounded LLM repair loop with this message.
    # If the source cannot be executed under the measuring stub, skip the gate
    # (that is a stub limitation, not a layout verdict) and let Manim decide.
    try:
        from templates._geometry import GeometryExecutionError, check_source

        try:
            violations = check_source(
                scene_py.read_text(encoding="utf-8"),
                box_tol=0.1, overlap_min=0.05, frame_tol=0.05,
            )
        except GeometryExecutionError as exc:
            print(f"[geometry-gate] skipped (unmeasurable source): {exc}")
            violations = []
    except Exception as exc:  # noqa: BLE001 — gate must never take down a render
        print(f"[geometry-gate] unavailable: {exc}")
        violations = []
    if violations:
        details = "\n".join(
            f"- [{v['kind']} beat={v.get('beat', '?')}] {v['detail']}"
            for v in violations
        )
        _write_result({
            "status": "failure",
            "failure_category": "geometry_validation_error",
            "failure_message": (
                "Scene layout failed geometry validation (measured with real "
                "text metrics before rendering):\n" + details + "\n"
                "Fix the named text in the identified beat and overflow axis: "
                "shorten or wrap it, fit it within both the available width and "
                "height, widen its shape, or reposition the colliding elements. "
                "Keep all content within the 14.2 x 8.0 frame."
            ),
        })
        sys.exit(1)

    quality_flag = {
        "low_quality": "-ql",
        "medium_quality": "-qm",
        "high_quality": "-qh",
        "production_quality": "-qk",
    }.get(quality, "-qm")

    with tempfile.TemporaryDirectory(prefix="manim-work-") as work_dir:
        work = Path(work_dir)
        shutil.copy(scene_py, work / "scene.py")
        media_dir = work / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        # Keep voiceovers in /app/output so the runner can recover them even
        # when an infrastructure timeout stops this container. A later render
        # attempt seeds /app/input/voiceovers with that recovered cache.
        voiceover_cache_dir = output_dir / "voiceovers"
        seeded_cache_dir = input_dir / "voiceovers"
        if seeded_cache_dir.exists():
            shutil.copytree(
                seeded_cache_dir,
                voiceover_cache_dir,
                dirs_exist_ok=True,
            )
        voiceover_cache_dir.mkdir(parents=True, exist_ok=True)
        (media_dir / "voiceovers").symlink_to(
            voiceover_cache_dir,
            target_is_directory=True,
        )

        try:
            from voiceover_prefetch import prefetch_voiceovers

            prefetched = prefetch_voiceovers(
                scene_py.read_text(encoding="utf-8"),
                voiceover_cache_dir,
            )
            if prefetched is None:
                print(
                    "[tts-prefetch] no statically recognizable narration plan; "
                    "using inline synthesis",
                    flush=True,
                )
            elif prefetched:
                print(
                    f"[tts-prefetch] generated {prefetched} narration segments in parallel",
                    flush=True,
                )
            else:
                print("[tts-prefetch] all recognized narration segments were cached", flush=True)
        except Exception as exc:
            _write_result({
                "status": "failure",
                "failure_category": "infrastructure_error",
                "failure_message": f"Parallel TTS pre-generation failed: {exc}",
            })
            sys.exit(1)

        cmd = [
            "manim", "render",
            str(work / "scene.py"),
            scene_class,
            quality_flag,
            f"--media_dir={media_dir}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        log = proc.stdout + proc.stderr
        (output_dir / "render.log").write_text(log, encoding="utf-8")

        if proc.returncode != 0:
            connection_markers = (
                "APIConnectionError",
                "ConnectError",
                "Name or service not known",
                "Temporary failure in name resolution",
            )
            connection_failure = any(marker in log for marker in connection_markers)
            category = "infrastructure_error" if connection_failure else "source_error"
            summary = (
                "TTS could not connect to LiteLLM from the Manim renderer."
                if connection_failure
                else f"manim exited with code {proc.returncode}."
            )
            _write_result({
                "status": "failure",
                "failure_category": category,
                "failure_message": summary + "\n" + _failure_excerpt(log),
            })
            sys.exit(1)

        # Filter out partial movie files and match exactly by scene class name,
        # same as run_manim_scene() does for the standalone script.
        video_files = [
            p for p in sorted(media_dir.rglob("*.mp4"))
            if "partial_movie_files" not in str(p) and p.stem == scene_class
        ]
        if not video_files:
            _write_result({
                "status": "failure",
                "failure_category": "render_error",
                "failure_message": f"Manim produced no .mp4 output for scene class '{scene_class}'",
            })
            sys.exit(1)

        final_video = output_dir / "video.mp4"
        shutil.copy(video_files[0], final_video)

        # VoiceoverScene subcaptions make Manim write <SceneClass>.srt beside the
        # MP4. Export it so the pipeline can publish captions for this video.
        srt_path = video_files[0].with_suffix(".srt")
        if srt_path.exists():
            shutil.copy(srt_path, output_dir / "captions.srt")

        ffprobe = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(final_video),
            ],
            capture_output=True,
            text=True,
        )
        actual_duration = (
            float(ffprobe.stdout.strip())
            if ffprobe.returncode == 0 and ffprobe.stdout.strip()
            else expected_duration
        )

        audio_probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(final_video),
            ],
            capture_output=True,
            text=True,
        )
        has_audio = audio_probe.returncode == 0 and "audio" in audio_probe.stdout
        if not has_audio:
            _write_result({
                "status": "failure",
                "failure_category": "render_error",
                "failure_message": (
                    "Rendered Manim explainer contains no audio stream. "
                    "Use VoiceoverScene and synchronize animations with self.voiceover()."
                ),
            })
            sys.exit(1)

        if os.environ.get("MANIM_BRAND_OUTRO", "on").strip().lower() != "off":
            outro_error = _append_brand_outro(final_video)
            if outro_error:
                _write_result({
                    "status": "failure",
                    "failure_category": "infrastructure_error",
                    "failure_message": "Brand outro splice failed: " + outro_error,
                })
                sys.exit(1)
            duration_probe = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    str(final_video),
                ],
                capture_output=True,
                text=True,
            )
            if duration_probe.returncode == 0 and duration_probe.stdout.strip():
                actual_duration = float(duration_probe.stdout.strip())

        _write_result({
            "status": "success",
            "duration_seconds": actual_duration,
            "has_audio": True,
        })


# ── Env validation ─────────────────────────────────────────────────────────────

def _validate_env() -> None:
    try:
        load_lite_llm_settings()
    except ValueError as exc:
        sys.exit(f"Error: {exc}")


# ── Main ───────────────────────────────────────────────────────────────────────

def _run_controller_mode(args: "argparse.Namespace") -> None:
    """Delegate to the canonical ManimGenerationController.

    Reads LITE_LLM_BASE_URL / LITE_LLM_API_KEY from the environment (shared with all pipeline tools).
    Produces a ManimVideoOutput for each scene derived from the brief and writes
    the result manifest JSON to the output directory.

    This mode requires the learning_pipeline package to be importable.
    """
    import asyncio
    import json as _json

    try:
        from learning_pipeline.config import load_manim_settings, build_elearning_real_manim_registry
        from learning_pipeline.tools.elearning_bundle.contracts import AnimationBrief
        from learning_pipeline.tools.manim_video._controller import ManimGenerationController
        from learning_pipeline.tools.manim_video._render_runner import ContainerManimRenderRunner
        from learning_pipeline.tools.manim_video._template_catalog import ManimTemplateCatalog
        from learning_pipeline.tools.manim_video._source_policy import SourcePolicyValidator
        from learning_pipeline.tools.manim_video._manim_client import LiteLLMManimClient, LiteLLMManimSettings
        from learning_pipeline.tools.manim_video._contracts import ManimRenderPolicy
        from learning_pipeline.tools._agentic_policy import AgenticExecutionPolicy
        from learning_pipeline.runtime.artifact_store import FileArtifactStore
    except ImportError as exc:
        print(f"Error: --controller mode requires the learning_pipeline package: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        settings = load_manim_settings()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    script_path = Path(args.script)
    if not script_path.exists():
        sys.exit(f"Error: script not found: {script_path}")

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    script_text = load_input(script_path)
    print(f"\n[controller] Script: {script_path}  ({len(script_text):,} chars)")
    print("[controller] Planning scenes via legacy planner...")
    plan = plan_scenes(script_text, _DEFAULT_MODEL)
    (out / 'scene_plan.json').write_text(_json.dumps(plan, indent=2))
    print(f"  Course: {plan['course_title']}")

    store = FileArtifactStore(settings.artifact_store_root)

    llm_client = LiteLLMManimClient(LiteLLMManimSettings(
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
        model_name=settings.model_name,
    ))

    tts_import = "from tts_service import LiteLLMTTSService"
    tts_service_call = (
        f'LiteLLMTTSService(voice="{settings.tts_voice}", model="{settings.tts_model}", transcription_model=None)'
    )

    quality_map = {'l': 'low', 'm': 'standard', 'h': 'high', 'k': 'production'}

    async def _run_all():
        controller = ManimGenerationController(
            artifact_store=store,
            llm_client=llm_client,
            render_runner=ContainerManimRenderRunner(
                image=settings.docker_image,
                timeout_seconds=ManimRenderPolicy().render_timeout_seconds,
                cpu_limit=settings.cpu_limit,
                memory_limit=settings.memory_limit,
                lite_llm_base_url=settings.litellm_base_url,
                lite_llm_api_key=settings.litellm_api_key,
                docker_network=settings.docker_network,
            ),
            template_catalog=ManimTemplateCatalog(),
            source_validator=SourcePolicyValidator(),
            tts_import=tts_import,
            tts_service_call=tts_service_call,
            policy=AgenticExecutionPolicy(),
            render_policy=ManimRenderPolicy(),
        )
        context_bytes = _json.dumps(plan, ensure_ascii=False).encode("utf-8")
        results = {}
        for i, scene in enumerate(plan['scenes'], 1):
            sid = scene['id']
            print(f"\n[controller] Scene {i}/{len(plan['scenes'])}: {scene['title']}  [{scene.get('visual_type', 'free_form')}]")
            brief = AnimationBrief(
                animation_id=sid,
                source_scene_ids=(sid,),
                learning_objective=scene.get('title', sid),
                teaching_purpose='deliver',
                visual_direction=scene.get('visual_type', 'free_form'),
                narration_script=scene.get('scene_narration'),
                quality_profile=quality_map.get(args.quality, 'high'),
            )
            try:
                output = await controller.run(
                    brief,
                    workflow_id='cli-run',
                    task_id=f'scene-{i}',
                    context_bytes=context_bytes,
                    context_hash=hashlib.sha256(context_bytes).hexdigest(),
                )
                results[sid] = {'status': 'success', 'video_uri': output.video_uri}
                print(f"  [controller] → {output.video_uri}")
            except Exception as exc:
                results[sid] = {'status': 'error', 'message': str(exc)}
                print(f"  [controller] ✗ {exc}")

        (out / 'controller_results.json').write_text(_json.dumps(results, indent=2))
        print(f"\n[controller] Results written to {out}/controller_results.json")

    asyncio.run(_run_all())


def main():
    ap = argparse.ArgumentParser(
        description="Generate a narrated e-learning video course from a script"
    )
    ap.add_argument('--script',    default='input/eho_script.txt',
                    help='Path to the input file: plain text transcript or .json RLO document')
    ap.add_argument('--output',    default='video_output',
                    help='Output directory')
    ap.add_argument('--voice',     default=os.environ.get('VOICE'),
                    help='TTS voice name. Also reads VOICE env var. Default: Kore.')
    ap.add_argument('--quality',   default='h',
                    choices=['l', 'm', 'h', 'k'],
                    help='Manim render quality: l=480p15, m=720p30, h=1080p60 (default), k=4K60')
    ap.add_argument('--no-render', action='store_true',
                    help='Skip Manim rendering — generates .py scene files only')
    ap.add_argument('--controller', action='store_true',
                    help=(
                        'Delegate to canonical ManimGenerationController '
                        '(requires learning_pipeline package and LITELLM_* env vars). '
                        'Overrides --no-render.'
                    ))
    ap.add_argument('--render', action='store_true',
                    help=(
                        'Render mode: read pre-generated scene.py and request.json from '
                        '/app/input, run Manim, write video.mp4 and result.json to /app/output. '
                        'No LLM or TTS calls. Used by ContainerManimRenderRunner.'
                    ))
    args = ap.parse_args()

    if args.render:
        _run_render_mode()
        return

    if args.controller:
        _run_controller_mode(args)
        return

    voice = args.voice or _DEFAULT_VOICE

    _validate_env()

    script_path = Path(args.script)
    if not script_path.exists():
        sys.exit(f"Error: script not found: {script_path}")

    out = Path(args.output)
    scenes_dir = out / 'scenes'
    out.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(exist_ok=True)

    script_text = load_input(script_path)
    render = not args.no_render

    print(f"\nScript : {script_path}  ({len(script_text):,} chars)")
    print(f"Model  : {_DEFAULT_MODEL}")
    print(f"TTS    : LiteLLM  /  voice: {voice}")
    print(f"Render : {'yes — Manim + LiteLLM TTS' if render else 'no — code generation only'}")
    print(f"Output : {out.resolve()}\n")

    # 1 — Plan
    print("Step 1/3 — Planning scenes...")
    plan = plan_scenes(script_text, _DEFAULT_MODEL)
    (out / 'scene_plan.json').write_text(json.dumps(plan, indent=2))
    print(f"  Course: {plan['course_title']}")
    for i, s in enumerate(plan['scenes'], 1):
        print(f"  Scene {i}: {s['title']}  [{s['visual_type']}]")

    # 2 — Generate + render scenes
    total = len(plan['scenes'])
    print(f"\nStep 2/3 — Generating {total} scenes...")
    video_paths: list[Path] = []
    for i, scene in enumerate(plan['scenes'], 1):
        vp = process_scene(
            scene, i, total, scenes_dir, _DEFAULT_MODEL, voice, render,
            args.quality
        )
        if vp:
            video_paths.append(vp)

    # 3 — Concatenate
    if render:
        _finish_video(video_paths, out, scenes_dir)
    else:
        print("\nCode generation complete.")
        print(f"Scene files in: {scenes_dir}")
        print("Run without --no-render to produce video.")


if __name__ == '__main__':
    main()
