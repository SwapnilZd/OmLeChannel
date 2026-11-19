"""Render deterministic sample data for every implemented catalog design variant."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import yaml

from renderer import render_course_html
from schema import CourseContent

_FIXTURE = Path(__file__).parent.parent / "components" / "fixtures" / "corporate_designs.yaml"


def design_gallery_course(theme: str = "deloitte-green") -> CourseContent:
    document = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    screens = []
    for sequence, fixture in enumerate(document["screens"], start=1):
        screen = {
            "screen_id": f"design-{sequence:02d}-{fixture['layout_variant']}",
            "sequence": sequence,
            "rlo_source_refs": ["components[0].canonical_content"],
            "image_prompt": None,
            "image_path": None,
            **fixture,
        }
        screens.append(screen)
    return CourseContent(
        rlo_id="synthetic-corporate-design-gallery",
        rlo_version="1.0.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        theme_id=theme,
        screens=screens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", default="deloitte-green")
    parser.add_argument("--out", default="/generated/corporate-design-gallery.html")
    args = parser.parse_args()
    course = design_gallery_course(args.theme)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_course_html(course, args.theme), encoding="utf-8")
    print(f"Rendered {len(course.screens)} design variants → {output}")


if __name__ == "__main__":
    main()
