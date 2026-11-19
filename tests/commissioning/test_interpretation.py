import json
from pathlib import Path
from types import SimpleNamespace

from learning_commissioning.contracts import LearningCommissionRequest, LearningSearchIntent
from learning_commissioning.services.interpretation import (
    SearchIntentInterpreter,
    deterministic_fallback,
)
from learning_pipeline.contracts.common import Modality

_ROOT = Path(__file__).parents[2]


def _request():
    return LearningCommissionRequest.model_validate_json(
        (_ROOT / "examples/reference/commissioning/cohort-request.json").read_text()
    )


class FakeCompletions:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        import json as _json
        parsed = LearningSearchIntent.model_validate(_json.loads(_json.dumps(self.content))) if self.content else None
        return SimpleNamespace(
            id="response-1",
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=20, output_tokens=15),
        )


def _client(responses):
    return SimpleNamespace(responses=SimpleNamespace(parse=responses.parse))


async def test_interpreter_uses_one_structured_call_without_separate_cohort_fields():
    completions = FakeCompletions({
        "primary_subject": "stakeholder resistance during organizational change",
        "subject_facets": ["recognizing resistance signals", "Financial Services Context"],
        "skills": ["recognize resistance"],
        "desired_outcomes": ["Recognize common signals"],
        "required_concepts": ["resistance signals"],
        "excluded_concepts": [],
        "ambiguities": [],
        "search_queries": [
            "recognizing stakeholder resistance signals",
            "stakeholder resistance examples in Financial Services",
        ],
    })
    interpreter = SearchIntentInterpreter(client=_client(completions), model="course-generator-mini")
    intent, trace = await interpreter.interpret(_request())

    assert intent.subject_facets == ("recognizing resistance signals",)
    assert all("financial services" not in query.casefold() for query in intent.search_queries)
    assert all(not query.casefold().endswith(" in") for query in intent.search_queries)
    assert trace.warnings
    assert trace.model == "course-generator-mini"
    assert len(completions.calls) == 1
    sent_data = json.loads(completions.calls[0]["input"][1]["content"])
    assert set(sent_data) == {"request_text", "stated_goals"}
    assert completions.calls[0]["text_format"].__name__ == "LearningSearchIntent"


async def test_interpreter_falls_back_deterministically_and_caches_result():
    completions = FakeCompletions(error=RuntimeError("proxy unavailable"))
    interpreter = SearchIntentInterpreter(client=_client(completions), model="course-generator-mini")
    first = await interpreter.interpret(_request())
    second = await interpreter.interpret(_request())

    assert first == second
    assert len(completions.calls) == 1
    assert first[1].model is None
    assert "RuntimeError" in first[1].fallback_reason
    assert len(first[0].search_queries) == 2


async def test_interpreter_preserves_an_explicit_elearning_request():
    request = _request().model_copy(update={
        "request_text": "Create an e-learning module about assigning ownership with RACI."
    })
    completions = FakeCompletions({
        "primary_subject": "RACI ownership assignment",
        "requested_modality": "elearning",
        "subject_facets": ["RACI ownership assignment"],
        "search_queries": ["RACI responsible accountable consulted informed"],
    })
    intent, _ = await SearchIntentInterpreter(
        client=_client(completions), model="request-interpreter"
    ).interpret(request)

    assert intent.requested_modality == Modality.ELEARNING
    assert "learning" not in intent.search_queries[0].casefold()


def test_deterministic_fallback_preserves_modality_but_removes_it_from_search():
    request = _request().model_copy(update={
        "request_text": "I would prefer a podcast about setting SMART goals."
    })

    intent = deterministic_fallback(request)

    assert intent.requested_modality == Modality.PODCAST
    assert "podcast" not in intent.primary_subject.casefold()
    assert all("podcast" not in query.casefold() for query in intent.search_queries)


def test_deterministic_fallback_does_not_treat_rejected_modality_as_requested():
    request = _request().model_copy(update={
        "request_text": "I do not want a podcast; teach me how to use RACI."
    })

    intent = deterministic_fallback(request)

    assert intent.requested_modality is None
