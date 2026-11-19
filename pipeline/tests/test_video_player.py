from __future__ import annotations

import subprocess
from pathlib import Path


_COMPONENTS = Path(__file__).resolve().parents[1] / "components"


def test_video_template_renders_accessible_caption_toggle_conditionally():
    template = (_COMPONENTS / "templates" / "video_player.html.j2").read_text()
    assert template.count("{% if s.captions_path %}") == 2
    assert 'class="video-cc-toggle"' in template
    assert 'aria-pressed="true"' in template
    assert 'aria-label="Turn captions off"' in template
    assert 'onclick="toggleCaptions(this)"' in template


def test_caption_toggle_changes_only_its_own_video_track():
    base_js = _COMPONENTS / "base.js"
    script = f"""
const fs = require('fs');
eval(fs.readFileSync({str(base_js)!r}, 'utf8'));

function fixture() {{
  const track = {{mode: 'showing'}};
  const video = {{textTracks: [track]}};
  const frame = {{querySelector: selector => selector === 'video' ? video : null}};
  const attrs = {{'aria-pressed': 'true', 'aria-label': 'Turn captions off'}};
  const button = {{
    closest: selector => selector === '.video-frame' ? frame : null,
    getAttribute: name => attrs[name],
    setAttribute: (name, value) => {{ attrs[name] = value; }},
  }};
  return {{track, attrs, button}};
}}

const first = fixture();
const second = fixture();
toggleCaptions(first.button);
if (first.track.mode !== 'disabled') process.exit(1);
if (first.attrs['aria-pressed'] !== 'false') process.exit(2);
if (first.attrs['aria-label'] !== 'Turn captions on') process.exit(3);
if (second.track.mode !== 'showing') process.exit(4);
toggleCaptions(first.button);
if (first.track.mode !== 'showing') process.exit(5);
if (first.attrs['aria-pressed'] !== 'true') process.exit(6);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
