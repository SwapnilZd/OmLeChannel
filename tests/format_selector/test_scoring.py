"""Deterministic scoring policy tests — Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from learning_pipeline.contracts import CourseBlueprint
from learning_pipeline.contracts.common import Modality
from learning_pipeline.contracts.format_selection import (
    DeliveryConstraints,
    FormatSelectionMode,
    FormatSelectionRequest,
    ModalityEvaluation,
    ModalityFeasibility,
)
from learning_pipeline.format_selector.profiles import MODALITY_PROFILES, PODCAST_PROFILE
from learning_pipeline.format_selector.scoring import (
    SCORING_POLICY_VERSION,
    score_modality,
    select_best,
)

_BP_PATH = Path(__file__).parents[2] / "examples" / "reference" / "podcast" / "course_blueprint.json"


def _load_blueprint() -> CourseBlueprint:
    return CourseBlueprint.model_validate_json(_BP_PATH.read_text(encoding="utf-8"))


def _auto_request(**overrides) -> FormatSelectionRequest:
    defaults = dict(request_id="req-01", blueprint_id="bp-01", mode=FormatSelectionMode.AUTO)
    defaults.update(overrides)
    return FormatSelectionRequest(**defaults)


def _make_eval(modality: Modality, score: float, feasible: bool = True) -> ModalityEvaluation:
    return ModalityEvaluation(
        modality=modality,
        feasible=feasible,
        blockers=() if feasible else ("not available",),
        factors=(),
        total_score=score,
    )


# ── Policy version ────────────────────────────────────────────────────────────


def test_scoring_policy_version_is_stable() -> None:
    assert SCORING_POLICY_VERSION == "format_scoring_v2"


# ── score_modality returns ModalityEvaluation ─────────────────────────────────


def test_score_modality_returns_evaluation() -> None:
    blueprint = _load_blueprint()
    request = _auto_request()
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    assert isinstance(eval_, ModalityEvaluation)


def test_score_modality_feasible_true() -> None:
    blueprint = _load_blueprint()
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, _auto_request(), blueprint)
    assert eval_.feasible is True


def test_score_modality_no_blockers() -> None:
    blueprint = _load_blueprint()
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, _auto_request(), blueprint)
    assert eval_.blockers == ()


# ── Preferred modality factor ─────────────────────────────────────────────────


def test_preferred_modality_first_gets_max_score() -> None:
    blueprint = _load_blueprint()
    request = _auto_request(preferred_modalities=(Modality.PODCAST,))
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    pref_factor = next(f for f in eval_.factors if f.factor == "preferred_modality_order")
    assert pref_factor.score == 10.0


def test_preferred_modality_second_gets_lower_score() -> None:
    blueprint = _load_blueprint()
    request = _auto_request(preferred_modalities=(Modality.VIDEO, Modality.PODCAST))
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    pref_factor = next(f for f in eval_.factors if f.factor == "preferred_modality_order")
    assert pref_factor.score == 8.0


def test_non_preferred_modality_has_no_preference_factor() -> None:
    blueprint = _load_blueprint()
    request = _auto_request(preferred_modalities=(Modality.VIDEO,))
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    assert not any(f.factor == "preferred_modality_order" for f in eval_.factors)


# ── Screen-free preference factor ─────────────────────────────────────────────


def test_screen_free_compatible_modality_gets_bonus() -> None:
    blueprint = _load_blueprint()
    request = _auto_request(constraints=DeliveryConstraints(screen_free_preferred=True))
    eval_ = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    compat = next(f for f in eval_.factors if f.factor == "screen_free_compatible")
    assert compat.score == 5.0


def test_screen_free_incompatible_modality_gets_penalty() -> None:
    blueprint = _load_blueprint()
    video_profile = MODALITY_PROFILES[Modality.VIDEO]
    request = _auto_request(constraints=DeliveryConstraints(screen_free_preferred=True))
    eval_ = score_modality(Modality.VIDEO, video_profile, request, blueprint)
    incompat = next(f for f in eval_.factors if f.factor == "screen_free_incompatible")
    assert incompat.score < 0


# ── Instructional scope factor ───────────────────────────────────────────────


def test_focused_scope_favors_podcast() -> None:
    blueprint = _load_blueprint().model_copy(update={
        "assessment_strategy": "Learner reflection only.",
    })
    request = _auto_request()
    podcast = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    elearning = score_modality(
        Modality.ELEARNING,
        MODALITY_PROFILES[Modality.ELEARNING],
        request,
        blueprint,
    )
    scope = next(f for f in podcast.factors if f.factor == "instructional_scope")
    assert scope.score > 0
    assert podcast.total_score > elearning.total_score


def test_broad_multi_rlo_scope_favors_elearning() -> None:
    blueprint = _load_blueprint()
    base_ref = blueprint.ordered_rlo_refs[0]
    refs = tuple(
        base_ref.model_copy(update={"rlo_id": f"rlo-generic-{index}", "order": index})
        for index in range(1, 5)
    )
    broad_blueprint = blueprint.model_copy(update={
        "ordered_rlo_refs": refs,
        "source_rlo_versions": {ref.rlo_id: ref.rlo_version for ref in refs},
    })
    request = _auto_request()
    podcast = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, broad_blueprint)
    elearning = score_modality(
        Modality.ELEARNING,
        MODALITY_PROFILES[Modality.ELEARNING],
        request,
        broad_blueprint,
    )
    podcast_scope = next(f for f in podcast.factors if f.factor == "instructional_scope")
    elearning_scope = next(f for f in elearning.factors if f.factor == "instructional_scope")
    assert podcast_scope.score < 0
    assert elearning_scope.score > 0
    assert select_best((podcast, elearning), request) == Modality.ELEARNING


def test_production_cost_does_not_influence_pedagogical_selection() -> None:
    blueprint = _load_blueprint()
    for modality, profile in MODALITY_PROFILES.items():
        evaluation = score_modality(modality, profile, _auto_request(), blueprint)
        assert not any(f.factor == "production_cost_class" for f in evaluation.factors)


# ── Scoring is deterministic ──────────────────────────────────────────────────


def test_identical_inputs_produce_identical_score() -> None:
    blueprint = _load_blueprint()
    request = _auto_request()
    e1 = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    e2 = score_modality(Modality.PODCAST, PODCAST_PROFILE, request, blueprint)
    assert e1.total_score == e2.total_score
    assert e1.model_dump_json() == e2.model_dump_json()


# ── select_best picks highest score ──────────────────────────────────────────


def test_select_best_returns_highest_scoring() -> None:
    evaluations = (
        _make_eval(Modality.PODCAST, 5.0),
        _make_eval(Modality.VIDEO, 2.0),
    )
    assert select_best(evaluations, _auto_request()) == Modality.PODCAST


def test_select_best_ignores_infeasible() -> None:
    evaluations = (
        _make_eval(Modality.PODCAST, 5.0, feasible=False),
        _make_eval(Modality.VIDEO, 2.0, feasible=True),
    )
    assert select_best(evaluations, _auto_request()) == Modality.VIDEO


def test_select_best_no_feasible_raises() -> None:
    evaluations = (
        _make_eval(Modality.PODCAST, 5.0, feasible=False),
    )
    with pytest.raises(ValueError):
        select_best(evaluations, _auto_request())


# ── Tie-breaking is documented and deterministic ──────────────────────────────


def test_tiebreaker_is_alphabetical_ascending() -> None:
    # "elearning" < "podcast" < "video" alphabetically
    # So elearning beats podcast beats video on equal scores.
    evaluations = (
        _make_eval(Modality.PODCAST, 0.0),
        _make_eval(Modality.VIDEO, 0.0),
    )
    # "podcast" < "video" → podcast wins
    assert select_best(evaluations, _auto_request()) == Modality.PODCAST


def test_tiebreaker_is_stable_across_calls() -> None:
    evaluations = (
        _make_eval(Modality.ELEARNING, 3.0),
        _make_eval(Modality.PODCAST, 3.0),
        _make_eval(Modality.VIDEO, 3.0),
    )
    request = _auto_request()
    result1 = select_best(evaluations, request)
    result2 = select_best(evaluations, request)
    assert result1 == result2
