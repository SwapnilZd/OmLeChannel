import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from grounding import SourceReferenceError, resolve_rlo_ref  # noqa: E402


def test_resolves_open_shaped_nested_content():
    source = {"components": [{"canonical_content": {"groups": [["neutral value"]]}}]}
    assert resolve_rlo_ref(source, "components[0].canonical_content.groups[0][0]") == "neutral value"


@pytest.mark.parametrize("path", ["components[1]", "components.0", "components[0]missing", ""])
def test_rejects_invalid_references(path):
    with pytest.raises(SourceReferenceError):
        resolve_rlo_ref({"components": [{}]}, path)
