"""Shared rendering utilities for per-template validator scripts."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from llm_gateway import ModelAlias

STUB_IMPORT = "from tts_service import LiteLLMTTSService"
STUB_CALL = (
    f'LiteLLMTTSService(voice="Kore", model="{ModelAlias.MANIM_SPEECH_SYNTHESIS}", '
    'transcription_model=None)'
)


def make_static(code: str) -> str:
    """Strip TTS so the scene renders without API keys."""
    code = re.sub(r"^from manim_voiceover\b.*\n", "", code, flags=re.MULTILINE)
    code = re.sub(r"^\s*self\.set_speech_service\(.*\)\n", "", code, flags=re.MULTILINE)
    code = code.replace("(VoiceoverScene)", "(Scene)")
    code = re.sub(
        r'( +)with self\.voiceover\(text="(?:[^"\\]|\\.)*"\) as tracker:',
        r"\1if True:  # preview",
        code,
    )
    # Voiceover blocks reference tracker.duration in many shapes
    # (d = tracker.duration, _rt(tracker.duration, ...), self.wait(...)) —
    # pin them all to a short preview duration.
    code = code.replace("tracker.duration", "0.4")
    return code


def find_video(search_root: Path, class_name: str) -> Path | None:
    """Return the newest MP4 whose stem matches class_name, skipping partial files."""
    candidates = [
        p for p in search_root.rglob("*.mp4")
        if p.stem == class_name and "partial_movie_files" not in str(p)
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def render_template(
    template,
    fixture: dict,
    name: str,
    quality: str = "l",
    dry_run: bool = False,
    out_dir: Path | None = None,
) -> tuple[str, Path | None]:
    """Generate Python, optionally render with Manim, return (code, video_path)."""
    scene_id = f"validator_{name}"
    raw  = template.render(template.validate(fixture.copy()), scene_id, STUB_IMPORT, STUB_CALL)
    code = make_static(raw)

    out_dir = out_dir or (Path.cwd() / "preview")
    out_dir.mkdir(parents=True, exist_ok=True)
    py_file = out_dir / f"{scene_id}.py"
    py_file.write_text(code, encoding="utf-8")

    if dry_run:
        return code, None

    class_name = f"Scene_{scene_id}"
    manim_bin  = shutil.which("manim")
    cmd = ([manim_bin, f"-q{quality}", py_file.name, class_name] if manim_bin
           else [sys.executable, "-m", "manim", f"-q{quality}", py_file.name, class_name])

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(out_dir))
    if result.returncode != 0:
        tail = (result.stderr or result.stdout)[-600:].strip()
        print(f"    ✗  Manim error:\n{tail}")
        return code, None

    video = find_video(out_dir / "media" / "videos", class_name)
    return code, video


# ── HTML ──────────────────────────────────────────────────────────────────────

_HTML_STYLE = """<style>
* { box-sizing: border-box; margin: 0; padding: 0 }
body { background: #1a1a1a; color: #e0e0e0; font-family: "Segoe UI", Arial, sans-serif;
       padding: 24px; max-width: 1600px; margin: 0 auto }
h1  { color: #86BC25; font-size: 22px; margin-bottom: 20px;
      border-bottom: 1px solid #333; padding-bottom: 10px }
h2  { color: #86BC25; font-size: 16px; margin-bottom: 12px }
.grid   { display: grid; gap: 28px }
.card   { background: #242424; border: 1px solid #333; border-radius: 6px;
          padding: 20px; display: flex; flex-direction: column; gap: 16px }
.panels { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap }
video   { width: 480px; max-width: 100%; border: 1px solid #444;
          background: #000; border-radius: 3px; flex-shrink: 0 }
.no-video { width: 480px; height: 270px; background: #2a2a2a; border: 1px dashed #555;
            border-radius: 3px; display: flex; align-items: center;
            justify-content: center; color: #888; font-size: 13px; flex-shrink: 0 }
pre { background: #1e1e1e; border: 1px solid #333; border-radius: 3px;
      padding: 14px; overflow: auto; max-height: 480px; font-size: 11px;
      line-height: 1.5; flex: 1; min-width: 0; color: #cdd3de }
.hint { font-size: 12px; color: #75787B; border-top: 1px solid #333;
        padding-top: 10px }
</style>"""


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _card_html(name: str, code: str, video: Path | None, report_dir: Path, hint: str) -> str:
    if video:
        try:
            rel = video.relative_to(report_dir)
            media_el = f'<video src="{rel}" controls autoplay loop muted></video>'
        except ValueError:
            media_el = f'<video src="{video}" controls autoplay loop muted></video>'
    else:
        media_el = '<div class="no-video">render failed — check terminal</div>'

    return (
        f'<div class="card">'
        f'<h2>{name.replace("_", " ").title()}</h2>'
        f'<div class="panels">{media_el}'
        f'<pre>{_html_escape(code)}</pre>'
        f"</div>"
        f'<p class="hint">{hint}</p>'
        f"</div>"
    )


def build_single_html(name: str, code: str, video: Path | None, report_dir: Path) -> str:
    hint = (
        f"To tune layout: edit <code>templates/{name}/layout.py</code>, "
        f"then re-run <code>python validator.py</code> and refresh this page."
    )
    card  = _card_html(name, code, video, report_dir, hint)
    title = name.replace("_", " ").title()
    ok    = 1 if video else 0
    return (
        "<!doctype html>\n<html lang='en'>\n<head>\n"
        "<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>\n"
        f"<title>{title} Preview</title>\n"
        f"{_HTML_STYLE}\n"
        "</head>\n<body>\n"
        f"<h1>{title} Preview &nbsp; "
        f"<small style='color:#75787B;font-size:14px'>({ok}/1 rendered)</small></h1>\n"
        f'<div class="grid">\n{card}\n</div>\n'
        "</body>\n</html>"
    )


def build_html(results: list[tuple[str, str, Path | None]], report_dir: Path) -> str:
    hint = (
        "To tune layout: edit <code>layout.py</code> in the relevant template folder, "
        "then re-run <code>python scene_validator/validate.py</code> and refresh this page."
    )
    sections = [_card_html(n, c, v, report_dir, hint) for n, c, v in results]
    ok  = sum(1 for _, _, v in results if v)
    tot = len(results)
    return (
        "<!doctype html>\n<html lang='en'>\n<head>\n"
        "<meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>\n"
        "<title>Template Preview</title>\n"
        f"{_HTML_STYLE}\n"
        "</head>\n<body>\n"
        f"<h1>Manim Template Preview &nbsp; "
        f"<small style='color:#75787B;font-size:14px'>({ok}/{tot} rendered)</small></h1>\n"
        f'<div class="grid">\n{"".join(sections)}\n</div>\n'
        "</body>\n</html>"
    )
