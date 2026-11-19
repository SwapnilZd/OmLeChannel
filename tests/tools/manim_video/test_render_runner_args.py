"""ContainerManimRenderRunner docker-create argument construction."""
from __future__ import annotations

from learning_pipeline.tools.manim_video._render_runner import ContainerManimRenderRunner


def test_brand_outro_on_by_default() -> None:
    args = ContainerManimRenderRunner()._build_create_args()
    assert "MANIM_BRAND_OUTRO=on" in " ".join(args)


def test_brand_outro_off_passes_env() -> None:
    runner = ContainerManimRenderRunner(brand_outro=False)
    args = runner._build_create_args()
    assert "MANIM_BRAND_OUTRO=off" in " ".join(args)


def test_env_precedes_image_argument() -> None:
    args = ContainerManimRenderRunner()._build_create_args()
    env_idx = args.index("MANIM_BRAND_OUTRO=on")
    image_idx = args.index("manim-renderer:latest")
    assert env_idx < image_idx
