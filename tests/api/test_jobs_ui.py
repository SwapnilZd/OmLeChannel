from pathlib import Path


_ROOT = Path(__file__).parents[2]


def test_jobs_page_has_live_status_sections_and_visibility_aware_polling():
    html = (_ROOT / "api/templates/jobs.html").read_text()

    assert "In progress" in html
    assert "Completed" in html
    assert "Failed" in html
    assert "visibilitychange" in html
    assert "poll_after_ms" not in html  # the list controls bounded backoff centrally
    assert "/deliverables" in html
    assert "canceling?'cancel':'restart'" in html
    assert "Restart from checkpoint" in html
    assert "Cancel job" in html
    assert "job-grid job-header" in html
    assert "Deliverables" in html
    assert "grid-template-columns:minmax(240px,1fr) 160px 210px 250px" in html
    assert ".actions{display:flex;flex-direction:column" in html
    assert "Open course" in html
    assert "/preview/" in html
    assert 'target="_blank" rel="noopener"' in html
    assert "credentials:'include'" in html
    assert "const base='/commissioning-api'" in html
    assert "Tracked cost includes model calls and podcast audio" in html
    assert "/cost`" in html
    assert "HeyGen cost is not included" in html


def test_commission_page_tracks_generation_beyond_blueprint_assembly():
    html = (_ROOT / "api/templates/commission.html").read_text()

    assert "job.status==='completed'" in html
    assert "job.blueprint_available" in html
    assert "View all jobs" in html
    assert "Download" in html
    assert "credentials:'include'" in html
    assert "const commissioningBase = '/commissioning-api'" in html


def test_commission_page_uses_a_lean_individual_request():
    html = (_ROOT / "api/templates/commission.html").read_text()

    assert "What would you like to learn?" in html
    assert "final outcomes will be grounded in the selected RLOs" in html
    assert "Specific outcomes" not in html
    assert "Audience roles" not in html
    assert "Maximum minutes" not in html
    assert "Industry behavior" not in html
    assert "Confirmation actor" not in html
    assert "name@deloitte.com" not in html
    assert "roles: []" in html
    assert "stated_goals: [], duration_limit_minutes: null" in html
    assert "confirmation_actor:'self-service-ui'" in html
    assert "globalThis.crypto?.randomUUID?.()" in html
    assert "Date.now()" in html


def test_commission_page_only_presents_curated_matching_content():
    html = (_ROOT / "api/templates/commission.html").read_text()

    assert "decision.recommendation==='include'" in html
    assert "matchingCandidates.map" in html
    assert "Matching RLO content" in html
    assert "Why this content matches" in html
    assert "decision.relationship_to_other_candidates" not in html
