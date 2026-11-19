from pathlib import Path


_ROOT = Path(__file__).parents[2]


def _review_template() -> Path:
    source_tree = _ROOT / "api/templates/rlo_drafts.html"
    return source_tree if source_tree.exists() else _ROOT / "templates/rlo_drafts.html"


def test_rlo_review_exposes_provenance_labels_filters_and_export():
    html = _review_template().read_text()

    assert "From the source" in html
    assert "Combined from source material" in html
    assert "Added domain knowledge" in html
    assert "Learning structure only" in html
    assert "Learning design" in html
    assert "Partly met" in html
    assert "Needs attention" in html
    assert "minor writing note" in html
    assert "Affected content:" in html
    assert "findingLocation" in html
    assert "Scoped revision" in html
    assert "no more than two model calls" in html
    assert "/export" in html
    assert "/review-metadata" in html
    assert "provenance-filter" in html
