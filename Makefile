.PHONY: manim-image manim-geometry-regressions manim-layout-audit test up-commissioning

# The renderer image must be built with the REPO ROOT as context — it copies
# llm_gateway/, manim/templates/, and brand/outro.mp4, which live outside
# manim/. (`docker build ./manim` will always fail.)
manim-image:
	docker build -f manim/Dockerfile -t manim-renderer:latest .

# Measures real text geometry of every template at worst-case bindings
# (frame bounds, text-in-box containment, label collisions). Needs the
# renderer image; exits non-zero on any finding.
manim-layout-audit:
	docker run --rm --entrypoint python3 -w /tmp -v "$(CURDIR)":/repo:ro \
		manim-renderer:latest /repo/manim/templates/audit_layout.py

# Exercises the scene-state semantics used by the pre-render geometry gate.
# These need real Manim animation objects and therefore run in the renderer.
manim-geometry-regressions:
	docker run --rm --entrypoint python3 -w /tmp -v "$(CURDIR)":/repo:ro \
		manim-renderer:latest /repo/manim/templates/geometry_regressions.py

test:
	python3 -m pytest tests -q --ignore=tests/container

up-commissioning:
	docker compose --profile commissioning up -d --build
