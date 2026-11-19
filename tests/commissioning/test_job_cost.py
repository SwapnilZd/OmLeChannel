from types import SimpleNamespace

from learning_commissioning.api.app import _langfuse_session_total, _podcast_cost_uris


def test_langfuse_session_cost_sums_trace_costs():
    assert _langfuse_session_total({
        "traces": [
            {"id": "a", "totalCost": 0.12},
            {"id": "b", "totalCost": "0.03"},
            {"id": "c", "totalCost": None},
        ]
    }) == 0.15


def test_langfuse_session_cost_is_unknown_without_costed_traces():
    assert _langfuse_session_total({"traces": [{"id": "a"}]}) is None


def test_podcast_cost_uris_excludes_heygen_estimate_reports():
    result = SimpleNamespace(deliverables=[
        SimpleNamespace(outputs={
            "costs_uri": "artifact://deliverables/job/podcast.costs.json",
            "cost_report_uri": "artifact://deliverables/job/heygen.costs.json",
        })
    ])

    assert _podcast_cost_uris(result) == [
        "artifact://deliverables/job/podcast.costs.json"
    ]
