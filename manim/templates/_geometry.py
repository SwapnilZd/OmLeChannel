"""Scene-geometry measurement shared by the pre-render gate and the audit.

Executes a generated Manim scene's construct() under a measuring stub (no TTS,
no rendering, no timing) and checks real Pango text geometry:

  FRAME-OUT     a mobject extends outside the 14.22 x 8 frame
  FRAME-TIGHT   Text closer to a frame edge than a caller-set margin (optional)
  BOX-OVERFLOW  Text whose center sits inside a Rectangle/Circle but whose
                bbox escapes that shape (text overflowing its card/box/hub)
  TXT-OVERLAP   two Text bboxes intersecting (label collisions)

Free-form scenes may replace content mid-scene (FadeOut one beat's text, show
the next beat's in the same place), so violations are measured per play() beat
against the then-visible mobject set — never against the union of everything
the scene ever showed.

Requires a Manim environment (Pango metrics). Import only inside the renderer
container or the layout-audit harness — never from workers or default tests.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from types import SimpleNamespace

from manim import Circle, Dot, Rectangle, Text
from manim.animation.animation import prepare_animation

FRAME_X = 7.111
FRAME_Y = 4.0

# Animations that remove their mobject from the visible set.
_REMOVER_ANIMATIONS = {"FadeOut", "Uncreate", "Unwrite", "ShrinkToCenter"}
# Animations that replace their mobject with target_mobject.
_REPLACEMENT_ANIMATIONS = {
    "ReplacementTransform", "TransformMatchingShapes", "TransformMatchingTex",
    "FadeTransform",
}


class GeometryExecutionError(RuntimeError):
    """The scene source could not be executed under the measurement stub.

    Distinct from a geometry violation: it means measurement was impossible
    (e.g. the source uses Scene APIs the stub does not model), not that the
    layout is wrong.
    """


class _DummySpeechService:
    def __init__(self, *args, **kwargs):
        pass


class MeasuringScene:
    """Stands in for VoiceoverScene during measurement.

    construct() runs for real — mobjects are created and positioned exactly as
    they would be for rendering — but play/wait/TTS are no-ops. Each play()
    records a snapshot of the visible mobject set for later measurement.
    """

    def __init__(self):
        self._visible: list = []
        self.snapshots: list[list] = []
        self.camera = SimpleNamespace(
            frame_width=FRAME_X * 2, frame_height=FRAME_Y * 2
        )

    # ── visible-set bookkeeping ────────────────────────────────────────────
    def _add(self, m) -> None:
        if m is not None and not any(m is v for v in self._visible):
            self._visible.append(m)

    def _drop(self, m) -> None:
        """Remove a mobject family using the same semantics a scene exposes.

        Generated scenes frequently add children separately, then remove a
        newly-created VGroup containing those children (or do the reverse).
        Exact-identity removal leaves phantom children in the measured scene
        and reports collisions that are not present in the rendered video.
        """
        if m is None:
            return
        removed_ids = {id(member) for member in m.get_family()}
        remaining = []
        for visible in self._visible:
            if id(visible) in removed_ids:
                continue
            self._prune_family(visible, removed_ids)
            remaining.append(visible)
        self._visible = remaining

    def _prune_family(self, parent, removed_ids: set[int]) -> None:
        children = list(getattr(parent, "submobjects", ()))
        direct = [child for child in children if id(child) in removed_ids]
        if direct:
            parent.remove(*direct)
        for child in children:
            if id(child) not in removed_ids:
                self._prune_family(child, removed_ids)

    @staticmethod
    def _flag(anim, name: str) -> bool:
        value = getattr(anim, name, False)
        if callable(value):
            try:
                value = value()
            except TypeError:
                value = False
        return bool(value)

    @staticmethod
    def _advance_to_end(anim) -> bool:
        """Run Manim's lifecycle to measure the animation's actual end state.

        Reading target_mobject directly is incorrect for there-and-back
        emphasis animations such as Indicate. Manim's own rate function and
        finish lifecycle determine whether the end state is the target or the
        original geometry.
        """
        try:
            anim.begin()
            anim.finish()
        except Exception:
            return False
        return True

    def _apply(self, anim) -> None:
        # Scene.play() normally converts the public `.animate` builder into a
        # concrete _MethodAnimation before beginning playback. Our lightweight
        # scene bypasses Scene.play(), so perform the same supported conversion
        # here to expose the computed target geometry.
        try:
            anim = prepare_animation(anim)
        except TypeError:
            pass
        subs = getattr(anim, "animations", None)
        if subs:  # AnimationGroup / LaggedStart / Succession
            for sub in subs:
                self._apply(sub)
            return
        m = getattr(anim, "mobject", None)
        if m is None:
            return
        name = type(anim).__name__
        is_remover = name in _REMOVER_ANIMATIONS or self._flag(anim, "remover") \
            or self._flag(anim, "is_remover")
        is_introducer = self._flag(anim, "introducer") \
            or self._flag(anim, "is_introducer")
        if is_remover:
            self._drop(m)
        elif name == "FadeTransform":
            self._drop(m)
            self._add(getattr(anim, "to_add_on_completion", None))
        elif name in _REPLACEMENT_ANIMATIONS:
            self._drop(m)
            self._add(getattr(anim, "target_mobject", None))
        elif name == "TransformFromCopy":
            # Its mobject is the destination and target_mobject is the source;
            # both remain visible after the animation.
            self._add(m)
        elif self._advance_to_end(anim):
            # A normal Transform mutates the source mobject, and Manim's
            # `.animate` builder computes the same end state during begin().
            # Keep its identity so later FadeOut/Transform calls find it.
            self._add(m)
        elif is_introducer:
            self._add(m)
        else:
            self._add(m)

    # ── Scene API surface ──────────────────────────────────────────────────
    def set_speech_service(self, *args, **kwargs):
        pass  # no TTS during measurement

    @contextmanager
    def voiceover(self, text=""):
        yield SimpleNamespace(duration=5.0)

    def play(self, *anims, **kwargs):
        for anim in anims:
            self._apply(anim)
        # Later transforms mutate mobjects in place. Snapshot copies prevent a
        # later beat from retroactively changing geometry already recorded for
        # an earlier beat.
        self.snapshots.append([m.copy() for m in self._visible])

    def add(self, *mobjects):
        for m in mobjects:
            self._add(m)

    def remove(self, *mobjects):
        for m in mobjects:
            self._drop(m)

    def wait(self, *args, **kwargs):
        pass  # timing is irrelevant to geometry

    def __getattr__(self, name):
        # Tolerate Scene APIs the stub does not model (bring_to_front, ...).
        return lambda *args, **kwargs: None


# ── Measurement ────────────────────────────────────────────────────────────────


def _bbox(m):
    return (m.get_left()[0], m.get_right()[0], m.get_bottom()[1], m.get_top()[1])


def _label(m):
    if isinstance(m, Text):
        t = getattr(m, "original_text", "")
        escaped = t.replace("\n", "\\n")
        return f'Text("{escaped[:96]}…")' if len(escaped) > 96 else f'Text("{escaped}")'
    return type(m).__name__


def _bounds(m) -> str:
    left, right, bottom, top = _bbox(m)
    return f"x={left:.2f}..{right:.2f}, y={bottom:.2f}..{top:.2f}"


def _family(visible):
    seen, members = set(), []
    for top in visible:
        for m in top.get_family():
            if id(m) not in seen:
                seen.add(id(m))
                members.append(m)
    return members


def _check_snapshot(visible, *, box_tol, overlap_min, frame_tol, edge_tight):
    family = _family(visible)
    texts = [m for m in family if isinstance(m, Text)
             and m.family_members_with_points()
             and getattr(m, "original_text", "").strip()]
    rects = [m for m in family if isinstance(m, Rectangle) and m.width >= 0.5]
    circles = [m for m in family if isinstance(m, Circle) and not isinstance(m, Dot)
               and m.width >= 0.9]

    findings: list[dict] = []

    def add(kind, detail):
        findings.append({"kind": kind, "detail": detail})

    for m in family:
        if not m.family_members_with_points():
            continue
        if isinstance(m, Text) and m not in texts:
            continue
        left, right, bottom, top = _bbox(m)
        margin = min(left + FRAME_X, FRAME_X - right, bottom + FRAME_Y, FRAME_Y - top)
        if margin < -frame_tol:
            add("FRAME-OUT", f"{_label(m)} exceeds the video frame by {-margin:.2f}")
        elif edge_tight is not None and margin < edge_tight and isinstance(m, Text):
            add("FRAME-TIGHT", f"{_label(m)} only {margin:.2f} from frame edge")

    for text_index, txt in enumerate(texts, 1):
        tl, tr, tb, tt = _bbox(txt)
        cx, cy = txt.get_center()[0], txt.get_center()[1]
        containing_rects = []
        for shape in rects:
            sl, sr, sb, st = _bbox(shape)
            if sl < cx < sr and sb < cy < st:
                containing_rects.append(shape)
        # Nested layout shapes are common. Checking the text against every
        # rectangle can associate it with an unrelated background panel; the
        # smallest containing shape is the best available proxy for its card.
        if containing_rects:
            shape = min(containing_rects, key=lambda item: item.width * item.height)
            sl, sr, sb, st = _bbox(shape)
            overages = {
                "left": max(0.0, sl - tl),
                "right": max(0.0, tr - sr),
                "bottom": max(0.0, sb - tb),
                "top": max(0.0, tt - st),
            }
            escaped = {axis: value for axis, value in overages.items() if value > box_tol}
            if escaped:
                axes = ", ".join(f"{axis}={value:.2f}" for axis, value in escaped.items())
                add(
                    "BOX-OVERFLOW",
                    f"text#{text_index} {_label(txt)} ({_bounds(txt)}, "
                    f"w={txt.width:.2f}, h={txt.height:.2f}) escapes nearest "
                    f"{type(shape).__name__} ({_bounds(shape)}, "
                    f"w={shape.width:.2f}, h={shape.height:.2f}); {axes}",
                )
        for shape in circles:
            scx, scy = shape.get_center()[0], shape.get_center()[1]
            r = shape.width / 2
            if (cx - scx) ** 2 + (cy - scy) ** 2 > r * r:
                continue
            worst = max(((x - scx) ** 2 + (y - scy) ** 2) ** 0.5
                        for x in (tl, tr) for y in (tb, tt))
            if worst > r + box_tol:
                add("BOX-OVERFLOW",
                    f"text#{text_index} {_label(txt)} ({_bounds(txt)}) escapes "
                    f"Circle(center=({scx:.2f}, {scy:.2f}), d={2 * r:.2f}) "
                    f"by {worst - r:.2f}")

    for i, a in enumerate(texts):
        al, ar, ab, at = _bbox(a)
        for j, b in enumerate(texts[i + 1:], i + 1):
            bl, br, bb, bt = _bbox(b)
            dx = min(ar, br) - max(al, bl)
            dy = min(at, bt) - max(ab, bb)
            if dx > overlap_min and dy > overlap_min:
                add("TXT-OVERLAP",
                    f"text#{i + 1} {_label(a)} ({_bounds(a)}) overlaps "
                    f"text#{j + 1} {_label(b)} ({_bounds(b)}); "
                    f"dx={dx:.2f}, dy={dy:.2f}")
    return findings


def check_source(
    source: str,
    *,
    box_tol: float = 0.03,
    overlap_min: float = 0.02,
    frame_tol: float = 0.0,
    edge_tight: float | None = None,
) -> list[dict]:
    """Execute scene source under the measuring stub and return violations.

    Returns a list of {"kind", "detail"} findings, deduplicated across beats.
    Raises GeometryExecutionError if the source cannot be executed under the
    stub — callers decide whether that is fatal (audit) or skippable (gate).
    """
    prepared = source.replace("from manim_voiceover import VoiceoverScene", "")
    prepared = re.sub(r"^from manim_voiceover\b.*$", "", prepared, flags=re.MULTILINE)
    prepared = re.sub(r"^from tts_service\b.*$", "", prepared, flags=re.MULTILINE)

    namespace = {
        "VoiceoverScene": MeasuringScene,
        "LiteLLMTTSService": _DummySpeechService,
    }
    try:
        exec(prepared, namespace)  # noqa: S102 — measurement of pipeline-generated code
        scene_cls = next(
            v for k, v in namespace.items()
            if isinstance(v, type) and issubclass(v, MeasuringScene)
            and v is not MeasuringScene
        )
        scene = scene_cls()
        scene.construct()
    except Exception as exc:
        raise GeometryExecutionError(repr(exc)) from exc

    snapshots = scene.snapshots or []
    if scene._visible and (not snapshots or snapshots[-1] != scene._visible):
        snapshots = [*snapshots, list(scene._visible)]

    findings: list[dict] = []
    seen: set[str] = set()
    for beat, visible in enumerate(snapshots, 1):
        for f in _check_snapshot(
            visible, box_tol=box_tol, overlap_min=overlap_min,
            frame_tol=frame_tol, edge_tight=edge_tight,
        ):
            if f["detail"] not in seen:
                seen.add(f["detail"])
                findings.append({**f, "beat": beat})
    return findings
