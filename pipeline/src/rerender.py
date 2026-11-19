import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from schema import CourseContent
from renderer import render_course_html


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-render course HTML from a saved plan JSON.")
    parser.add_argument("--plan", required=True, help="Path to the *.plan.json file.")
    parser.add_argument("--theme", default=None, help="Override theme ID (default: use theme_id stored in plan JSON).")
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    course = CourseContent.model_validate_json(plan_path.read_text(encoding="utf-8"))

    theme_id = args.theme or course.theme_id
    html = render_course_html(course, theme_id=theme_id)
    out_path = plan_path.with_suffix("").with_suffix(".html")
    out_path.write_text(html, encoding="utf-8")
    print(f"✓ Re-rendered (theme: {theme_id}) → {out_path}")


if __name__ == "__main__":
    main()
