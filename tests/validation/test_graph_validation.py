"""Unit tests for the shared DAG validator."""

from __future__ import annotations

import pytest

from learning_pipeline.validation.errors import CrossContractValidationError
from learning_pipeline.validation.graph import validate_dag

_OBJECT_TYPE = "node"


def test_valid_linear_chain_passes() -> None:
    validate_dag(
        ("a", "b", "c"),
        {"b": ("a",), "c": ("b",)},
        object_type=_OBJECT_TYPE,
    )


def test_valid_fan_in_passes() -> None:
    validate_dag(
        ("a", "b", "c"),
        {"c": ("a", "b")},
        object_type=_OBJECT_TYPE,
    )


def test_empty_graph_passes() -> None:
    validate_dag((), {}, object_type=_OBJECT_TYPE)


def test_single_node_no_deps_passes() -> None:
    validate_dag(("a",), {}, object_type=_OBJECT_TYPE)


def test_duplicate_node_ids_rejected() -> None:
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_dag(("a", "b", "a"), {}, object_type=_OBJECT_TYPE)
    assert exc_info.value.code == "duplicate_id"
    assert "a" in str(exc_info.value)


def test_dependency_on_unknown_node_rejected() -> None:
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_dag(("a",), {"a": ("missing",)}, object_type=_OBJECT_TYPE)
    assert exc_info.value.code == "missing_dependency"
    assert "missing" in str(exc_info.value)


def test_self_dependency_rejected() -> None:
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_dag(("a",), {"a": ("a",)}, object_type=_OBJECT_TYPE)
    assert exc_info.value.code == "dependency_cycle"
    assert "itself" in str(exc_info.value)


def test_two_node_cycle_rejected() -> None:
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_dag(
            ("a", "b"),
            {"a": ("b",), "b": ("a",)},
            object_type=_OBJECT_TYPE,
        )
    assert exc_info.value.code == "dependency_cycle"


def test_three_node_cycle_rejected() -> None:
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_dag(
            ("a", "b", "c"),
            {"a": ("c",), "b": ("a",), "c": ("b",)},
            object_type=_OBJECT_TYPE,
        )
    assert exc_info.value.code == "dependency_cycle"


def test_traversal_is_deterministic() -> None:
    for _ in range(5):
        with pytest.raises(CrossContractValidationError) as exc_info:
            validate_dag(
                ("z", "a", "m"),
                {"z": ("m",), "m": ("a",), "a": ("z",)},
                object_type=_OBJECT_TYPE,
            )
        assert exc_info.value.code == "dependency_cycle"


def test_object_type_appears_in_message() -> None:
    with pytest.raises(CrossContractValidationError) as exc_info:
        validate_dag(("x",), {"x": ("x",)}, object_type="custom_type")
    assert "custom_type" in str(exc_info.value)
