"""Thin command-line adapter over :func:`service.render_course`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rlo_schema import RLO, validate_rlo

from service import render_course


def _fetch_rlo_from_api(rlo_id: str) -> dict:
    api_url = os.environ.get("API_URL", "http://api:8000")
    with urllib.request.urlopen(f"{api_url}/api/rlos/{rlo_id}", timeout=10) as response:
        return json.loads(response.read())


def _load_rlo(path: str | None, rlo_id: str | None) -> tuple[RLO, str]:
    if rlo_id:
        raw = _fetch_rlo_from_api(rlo_id)
        slug = rlo_id
    else:
        source = Path(path or "").resolve()
        raw = json.loads(source.read_text(encoding="utf-8"))
        slug = source.stem
    validated, _ = validate_rlo(raw)
    return RLO.model_validate(validated), slug


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate browser-ready learning from a v1 RLO.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rlo", help="Path to an RLO JSON file.")
    source.add_argument("--rlo-id", help="RLO ID to fetch from the ingestion API.")
    parser.add_argument("--out", default="/generated", help="Output directory.")
    parser.add_argument("--theme", default="deloitte-green")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()

    rlo, slug = _load_rlo(args.rlo, args.rlo_id)
    print(f"Validated {rlo.id} v{rlo.version}; generating course…")
    result = render_course(
        rlo,
        theme=args.theme,
        generate_images=not args.no_images,
    )

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{slug}.html"
    content_path = out_dir / f"{slug}.course.json"
    plan_path = out_dir / f"{slug}.plan.json"
    html_path.write_text(result.html, encoding="utf-8")
    content_path.write_text(result.course.model_dump_json(indent=2), encoding="utf-8")
    plan_path.write_text(result.plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"Course HTML → {html_path}")
    print(f"Course data → {content_path}")
    print(f"Screen plan → {plan_path}")
    for warning in result.warnings:
        print(f"Warning: {warning}")


if __name__ == "__main__":
    main()
