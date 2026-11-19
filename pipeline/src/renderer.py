from pathlib import Path

import markupsafe
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from schema import CourseContent, ScreenContent

_COMPONENTS_DIR = Path(__file__).parent.parent / "components"
_TEMPLATES_DIR = _COMPONENTS_DIR / "templates"
_THEMES_DIR = _COMPONENTS_DIR / "themes"


def _brand_path() -> Path:
    candidates = (
        _COMPONENTS_DIR.parent / "brand",        # Docker: /app/brand
        _COMPONENTS_DIR.parent.parent / "brand", # repository checkout
    )
    for directory in candidates:
        path = directory / "deloitte.yaml"
        if path.exists():
            return path
    raise FileNotFoundError("Could not locate brand/deloitte.yaml")

_DEFAULT_THEME_ID = "deloitte-green"

_CSS = "<style>\n" + (_COMPONENTS_DIR / "base.css").read_text(encoding="utf-8") + "\n</style>"
_JS  = "<script>\n" + (_COMPONENTS_DIR / "base.js").read_text(encoding="utf-8") + "\n</script>"


def _paragraphs_filter(text: str) -> markupsafe.Markup:
    """Convert double-newline-separated text into HTML <p> blocks."""
    parts = [p.replace("\n", " ").strip() for p in str(text).split("\n\n") if p.strip()]
    return (
        markupsafe.Markup("".join(f"<p>{markupsafe.escape(p)}</p>" for p in parts))
        if parts
        else markupsafe.Markup("")
    )


def _first_sentence_filter(text: str) -> str:
    """Return only the first sentence — used for subtitle/tagline truncation."""
    cleaned = str(text).replace("\n", " ").strip()
    for delim in (".", "—", ";"):
        idx = cleaned.find(delim)
        if 0 < idx < 120:
            return cleaned[: idx + 1].strip()
    return cleaned[:100].strip()


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    env.filters["paragraphs"] = _paragraphs_filter
    env.filters["first_sentence"] = _first_sentence_filter
    return env


_env = _build_env()


def load_theme(theme_id: str) -> dict:
    theme_path = _THEMES_DIR / f"{theme_id}.yaml"
    if not theme_path.exists():
        theme_path = _THEMES_DIR / f"{_DEFAULT_THEME_ID}.yaml"
    brand = yaml.safe_load(_brand_path().read_text(encoding="utf-8")) or {}
    theme = yaml.safe_load(theme_path.read_text(encoding="utf-8")) or {}
    merged = {**brand, **theme}
    merged["palette"] = {**brand.get("palette", {}), **theme.get("palette", {})}
    merged["typography"] = {
        **brand.get("typography", {}),
        **theme.get("typography", {}),
    }
    return merged


def _theme_css_vars(theme: dict) -> str:
    palette = theme.get("palette", {})
    def resolve(value: str) -> str:
        return palette.get(value, value)

    lines = [
        f"  --brand-{k.replace('_', '-')}: {v};"
        for k, v in palette.items()
    ] + [
        f"  --{k.replace('_', '-')}: {resolve(v)};"
        for k, v in theme.get("colors", {}).items()
    ]
    r = theme.get("border_radius", 10)
    h_font = theme.get("typography", {}).get("heading_font", "Open Sans")
    b_font = theme.get("typography", {}).get("body_font", "Open Sans")
    lines += [
        f"  --r: {r}px;",
        f"  --h-font: '{h_font}', sans-serif;",
        f"  --b-font: '{b_font}', sans-serif;",
    ]
    return "<style>:root {\n" + "\n".join(lines) + "\n}</style>"


def _render_screen(screen: ScreenContent, theme: dict) -> str:
    tmpl = _env.get_template(f"{screen.type}.html.j2")  # type: ignore[union-attr]
    return tmpl.render(s=screen.model_dump(), theme=theme)


def render_course_html(course: CourseContent, theme_id: str = _DEFAULT_THEME_ID) -> str:
    theme = load_theme(theme_id)
    slides = "\n\n".join(_render_screen(s, theme) for s in course.screens)
    rlo_id_safe = course.rlo_id.replace("&", "&amp;").replace("<", "&lt;")
    rlo_ver_safe = course.rlo_version.replace("&", "&amp;").replace("<", "&lt;")
    gen_at_safe = course.generated_at.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Generated E-Learning — {rlo_id_safe}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://unpkg.com/reveal.js@5.1.0/dist/reveal.css" />
  <link rel="stylesheet" href="https://unpkg.com/reveal.js@5.1.0/dist/theme/white.css" />
  <!-- rlo: {rlo_id_safe} v{rlo_ver_safe} | {gen_at_safe} | theme: {theme.get('id', theme_id)} -->
  {_theme_css_vars(theme)}
  {_CSS}
</head>
<body>
<div class="reveal">
  <div class="slides">
{slides}
  </div>
</div>
<script src="https://unpkg.com/reveal.js@5.1.0/dist/reveal.js"></script>
<script>
Reveal.initialize({{
  width: 1280,
  height: 720,
  margin: 0.04,
  minScale: 0.2,
  maxScale: 2.0,
  hash: true,
  history: true,
  controls: true,
  progress: true,
  slideNumber: 'c/t',
  transition: 'fade',
  transitionSpeed: 'fast',
  center: false,
}});
</script>
{_JS}
</body>
</html>"""
