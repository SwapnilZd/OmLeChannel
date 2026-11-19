from pathlib import Path


_ROOT = Path(__file__).parents[2]
_TEMPLATES = (
    _ROOT / "api/templates" if (_ROOT / "api/templates").is_dir() else _ROOT / "templates"
)


def test_source_intake_links_ready_jobs_to_extraction_sandbox():
    html = (_TEMPLATES / "source_upload.html").read_text()

    assert "source-inspect" in html
    assert "node_count" in html
    assert "warning_count" in html


def test_extraction_sandbox_exposes_human_and_raw_views():
    html = (_TEMPLATES / "source_inspect.html").read_text()

    assert "Extraction Sandbox" in html
    assert "Original" in html
    assert "Docling extraction" in html
    assert "Visuals and written explanations" in html
    assert "Extraction diagnostics" in html
    assert "Generated segments" in html
    assert "Raw artifacts" in html
    assert "Detected text in visual" in html
    assert "Written explanation" in html
    assert "Start an objective job" in html
    assert "/api/objective-jobs" in html
    assert "/objective-jobs/" in html
    assert 'role="status" aria-live="polite"' in html


def test_objective_job_review_exposes_workflow_lineage_and_prompt_snapshots():
    html = (_TEMPLATES / "objective_job_review.html").read_text()

    assert "Objective Review" in html
    assert "Objective + Source Review" in html
    assert "Ready for RLO Planning" in html
    assert "Source availability for the seven RLO parts" in html
    assert "This is a search result, not proof" in html
    assert "Suggested Bloom" in html
    assert "Suggested kind" in html
    assert "Source lineage" in html
    assert "c.evidence_details||c.evidence" in html
    assert "Unassociated source material" in html
    assert "Excluded proposals" in html
    assert "Prompts used" in html
    assert "Curriculum coverage" in html
    assert "Curriculum domain" in html
    assert "Coverage needs refresh" in html
    assert "Source limitations" in html
    assert "Initial focused discovery" in html
    assert "Initial eligibility rationale" in html
    assert "Focused missing-performance target" in html
    assert "off-target" in html
    assert "Source claims" in html
    assert "View exact prompt" in html
    assert "Exact structured input" in html
    assert "Add related objective" in html
    assert "Split objective" in html
    assert "Merge with next" in html
    assert "Undo decision" in html
    assert "RLO generation started" in html
    assert "enable cross-RLO relationship and duplication checks" in html
    assert "model operations completed" in html
    assert 'id="act-bar"' in html
    assert "Export objectives to Excel" in html
    assert "Finalize approved objectives" in html
    assert '<button type="button" class="obj-item' in html
    assert "/candidates" in html
    assert "/reviews" in html
    assert "/advance" in html
    assert "Outside POC2 authoring scope" in html
    assert "/reclassify" in html
    assert 'disabled title="Outside POC2 authoring scope"' in html


def test_objective_job_list_exposes_processing_and_workflow_status():
    html = (_TEMPLATES / "objective_jobs.html").read_text()

    assert "Objective Jobs" in html
    assert "workflow_stage" in html
    assert "processing_status" in html
    assert "/api/objective-jobs" in html
