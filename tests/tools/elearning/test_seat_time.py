"""Tests for deterministic post-authoring seat-time estimation."""
from learning_pipeline.tools.elearning_bundle._seat_time import (
    SEAT_TIME_POLICY_VERSION,
    apply_seat_time_metadata,
    estimate_seat_time_minutes,
)


def _title(duration: str = "20 minutes") -> dict:
    return {
        "type": "title",
        "course_title": "A short course",
        "subtitle": "Learn the assigned material.",
        "hook": "Begin here.",
        "metadata": {"duration": duration, "duration_minutes": 20},
    }


def test_policy_is_versioned():
    assert SEAT_TIME_POLICY_VERSION == "elearning-seat-time-v1"


def test_model_authored_duration_does_not_influence_estimate():
    first = estimate_seat_time_minutes([_title("20 minutes")])
    second = estimate_seat_time_minutes([_title("200 minutes")])
    assert first == second


def test_more_learner_content_increases_estimate():
    short = [_title()]
    long = [
        _title(),
        {
            "type": "structured_list",
            "heading": "Details",
            "items": [{"body": "word " * 1400}],
        },
    ]
    assert estimate_seat_time_minutes(long) > estimate_seat_time_minutes(short)


def test_video_slot_reserves_time():
    without_video = estimate_seat_time_minutes([_title()])
    with_video = estimate_seat_time_minutes(
        [_title(), {"type": "video_slot", "title": "Watch the explanation"}]
    )
    assert with_video > without_video


def test_apply_overwrites_title_with_integer_estimate():
    screens = [_title()]
    minutes = apply_seat_time_metadata(screens)
    assert screens[0]["metadata"]["duration_minutes"] == minutes
    assert screens[0]["metadata"]["duration"] == f"About {minutes} minute"
