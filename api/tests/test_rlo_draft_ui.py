from pathlib import Path


_ROOT = Path(__file__).parents[2]
_TEMPLATES = (
    _ROOT / "api/templates" if (_ROOT / "api/templates").is_dir() else _ROOT / "templates"
)


def test_rlo_draft_review_page_exposes_accessible_human_review_controls():
    html = (_TEMPLATES / "rlo_drafts.html").read_text()

    assert "RLO Review" in html
    assert 'aria-labelledby="editor-heading"' in html
    assert 'for="draft-json"' in html
    assert 'role="status" aria-live="polite"' in html
    assert "Where the content came from" in html
    assert "Review checks" in html
    assert 'id="validation-summary"' in html
    assert "minor writing note" in html
    assert "Optional wording observations. They do not block approval." in html
    assert "Affected content:" in html
    assert "findingExcerpt" in html
    assert "Technical details" in html
    assert "Scoped revision" in html
    assert "Preview revision" in html
    assert "Confirm bounded revision" in html
    assert "/revision-options" in html
    assert "/revision-plan" in html
    assert "maximum_model_calls" in html
    assert "Revision history" in html
    assert "Learning design" in html
    assert 'id="instructional-approach"' in html
    assert "guidance_assessments" in html
    assert "View design suggestions" in html
    assert "Partly met means it uses a reasonable alternative" in html
    assert "Needs attention means a reviewer should decide" in html
    assert "guidanceOpen" in html
    assert "Instructional Designer decision" in html
    assert "Advanced authoring JSON" in html
    assert 'aria-label="Seven RLO parts"' in html
    assert "Request revision" in html
    assert "Approve and publish" in html
    assert "Technical generation details" in html
    assert "Download RLO JSON" in html
    assert 'id="download-rlo"' in html
    assert "/export" in html
    assert "credentials:'include'" in html
    assert "/api/rlo-drafts" in html
    assert "new URLSearchParams(location.search).get('draft')" in html
    assert "jobs[0]?.job_id" in html
    assert "data-lineage-id" in html
    assert "openLineageIds()" in html
    assert "restoreOpenLineages(openLineages)" in html
    assert "Generate a draft manually" not in html
    assert "Historical RLO outside the current POC2 scope" in html
    assert "fact-remember" in html


def test_all_admin_pages_share_primary_navigation():
    template_names = (
        "index.html",
        "commission.html",
        "jobs.html",
        "source_upload.html",
        "source_inspect.html",
        "objective_jobs.html",
        "objective_job_review.html",
        "rlo_drafts.html",
    )
    navigation_paths = (
        "/source-upload",
        "/objective-jobs",
        "/rlo-drafts",
        "/",
        "/commission",
        "/jobs",
        "/logout",
    )

    for name in template_names:
        html = (_TEMPLATES / name).read_text()
        assert '<header class="app-header">' in html
        assert html.index('<header class="app-header">') < html.index('class="layout')
        assert 'class="eyebrow"' not in html
        navigation_start = html.index("<nav")
        positions = [
            html.index(f'href="{path}"', navigation_start)
            for path in navigation_paths
        ]
        assert positions == sorted(positions)
