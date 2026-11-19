"""Extract and pre-generate literal Manim voice-over segments."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VoiceoverPrefetchPlan:
    voice: str
    model: str
    texts: tuple[str, ...]


def _static_loop_strings(
    target: ast.expr,
    iterable: ast.expr,
) -> dict[str, tuple[str, ...]]:
    """Resolve string values bound by a statically declared loop."""

    if not isinstance(iterable, (ast.List, ast.Tuple)):
        return {}
    rows = iterable.elts
    if isinstance(target, ast.Name):
        if all(
            isinstance(row, ast.Constant) and isinstance(row.value, str)
            for row in rows
        ):
            return {target.id: tuple(row.value for row in rows)}
        return {}
    if not isinstance(target, (ast.List, ast.Tuple)):
        return {}

    bindings: dict[str, tuple[str, ...]] = {}
    for index, item_target in enumerate(target.elts):
        if not isinstance(item_target, ast.Name):
            continue
        values: list[str] = []
        for row in rows:
            if not isinstance(row, (ast.List, ast.Tuple)) or index >= len(row.elts):
                break
            value = row.elts[index]
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                break
            values.append(value.value)
        else:
            bindings[item_target.id] = tuple(values)
    return bindings


def extract_voiceover_prefetch_plan(source: str) -> VoiceoverPrefetchPlan | None:
    """Return the literal TTS configuration and narration texts in *source*.

    Generated scenes are already source-policy validated before this runs. This
    parser deliberately ignores computed narration so those blocks retain the
    existing on-demand synthesis behavior during rendering.
    """
    tree = ast.parse(source)
    voice = None
    model = None
    texts: list[str] = []
    literal_strings: dict[str, str] = {}
    literal_iterables: dict[str, ast.expr] = {}
    loop_strings: dict[str, list[str]] = {}
    ambiguous_names: set[str] = set()

    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue

        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, (ast.List, ast.Tuple)):
                literal_iterables[target.id] = value
                continue
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                ambiguous_names.add(target.id)
                literal_strings.pop(target.id, None)
                continue
            existing = literal_strings.get(target.id)
            if existing is not None and existing != value.value:
                ambiguous_names.add(target.id)
                literal_strings.pop(target.id, None)
            elif target.id not in ambiguous_names:
                literal_strings[target.id] = value.value

    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        iterable = node.iter
        if isinstance(iterable, ast.Name):
            iterable = literal_iterables.get(iterable.id, iterable)
        for name, values in _static_loop_strings(node.target, iterable).items():
            loop_strings.setdefault(name, []).extend(values)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "LiteLLMTTSService":
            values = {
                keyword.arg: keyword.value.value
                for keyword in node.keywords
                if keyword.arg in {"voice", "model"}
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            }
            voice = values.get("voice", voice)
            model = values.get("model", model)
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "voiceover"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            continue
        text_node = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "text"),
            None,
        )
        resolved_texts: tuple[str, ...] = ()
        if isinstance(text_node, ast.Constant) and isinstance(text_node.value, str):
            resolved_texts = (text_node.value,)
        elif isinstance(text_node, ast.Name) and text_node.id not in ambiguous_names:
            if text_node.id in literal_strings:
                resolved_texts = (literal_strings[text_node.id],)
            else:
                resolved_texts = tuple(loop_strings.get(text_node.id, ()))
        for text in resolved_texts:
            normalized = " ".join(text.split())
            if normalized and normalized not in texts:
                texts.append(normalized)

    if not voice or not model or len(texts) < 2:
        return None
    return VoiceoverPrefetchPlan(voice=voice, model=model, texts=tuple(texts))


def prefetch_voiceovers(
    source: str,
    cache_dir: Path,
    *,
    max_workers: int = 4,
) -> int | None:
    """Populate the manim-voiceover cache for literal narration segments."""
    plan = extract_voiceover_prefetch_plan(source)
    if plan is None:
        return None

    from tts_service import LiteLLMTTSService

    service = LiteLLMTTSService(
        voice=plan.voice,
        model=plan.model,
        transcription_model=None,
        cache_dir=cache_dir,
    )
    return service.prefetch(plan.texts, max_workers=max_workers)
