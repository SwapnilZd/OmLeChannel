import pytest

from learning_pipeline.runtime.execution import ExecutorRegistry, UnregisteredTaskTypeError


class _Dummy:
    async def execute(self, context):
        return {}


def test_registration_succeeds():
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", _Dummy())
    assert "speech.synthesize" in registry.registered_task_types


def test_duplicate_registration_fails():
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", _Dummy())
    with pytest.raises(ValueError, match="already registered"):
        registry.register("speech.synthesize", _Dummy())


def test_empty_task_type_is_rejected():
    registry = ExecutorRegistry()
    with pytest.raises(ValueError):
        registry.register("", _Dummy())


def test_unknown_executor_lookup_fails():
    registry = ExecutorRegistry()
    with pytest.raises(UnregisteredTaskTypeError):
        registry.get("missing.type")


def test_registered_task_types_returns_frozenset():
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", _Dummy())
    task_types = registry.registered_task_types
    assert isinstance(task_types, frozenset)


def test_registered_task_types_is_a_snapshot():
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", _Dummy())
    snapshot = registry.registered_task_types
    registry.register("audio.assemble", _Dummy())
    assert "audio.assemble" not in snapshot


def test_registered_task_types_contains_all_registered():
    registry = ExecutorRegistry()
    registry.register("speech.synthesize", _Dummy())
    registry.register("audio.assemble", _Dummy())
    assert registry.registered_task_types == frozenset({"speech.synthesize", "audio.assemble"})
