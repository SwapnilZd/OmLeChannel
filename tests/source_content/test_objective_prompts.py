from pathlib import Path

from src.source_authoring import objectives
from src.source_authoring import prompt_assets
from src.source_authoring.prompt_assets import PROMPTS_ROOT, PromptAsset


def test_objective_prompts_are_named_versioned_markdown_assets():
    expected = {
        "practitioner_lenses.md",
        "structured_signal_detection.md",
        "sme_signal_detection.md",
        "candidate_formation.md",
        "candidate_reconciliation.md",
        "evidence_verification.md",
        "source_feature_inventory.md",
        "detail_enrichment.md",
        "decomposition_rules.md",
        "objective_classification.md",
        "objective_classification_repair.md",
        "classification_rules.md",
        "document_curriculum_blueprint.md",
        "objective_set_coverage_review.md",
        "coverage_gap_discovery.md",
        "gap_target_alignment.md",
        "related_objective_discovery.md",
        "objective_support_assessment.md",
    }
    assert {path.name for path in PROMPTS_ROOT.glob("*.md")} >= expected
    for filename in expected:
        text = (PROMPTS_ROOT / filename).read_text(encoding="utf-8")
        assert "Prompt ID: `" in text
        assert "Prompt Version: `" in text


def test_objective_service_uses_prompt_assets_not_inline_strings():
    executed_assets = (
        objectives.LENS_PROMPT,
        objectives.SIGNAL_PROMPT,
        objectives.FEATURE_PROMPT,
        objectives.PROPOSAL_PROMPT,
        objectives.CLASSIFICATION_PROMPT,
        objectives.CLASSIFICATION_REPAIR_PROMPT,
        objectives.BLUEPRINT_PROMPT,
        objectives.COVERAGE_PROMPT,
        objectives.GAP_PROMPT,
        objectives.TARGET_ALIGNMENT_PROMPT,
        objectives.RELATED_OBJECTIVE_PROMPT,
        objectives.SUPPORT_ASSESSMENT_PROMPT,
    )
    assert all(isinstance(asset, PromptAsset) for asset in executed_assets)
    assert len({asset.prompt_id for asset in executed_assets}) == len(executed_assets)
    assert Path(objectives.PROPOSAL_PROMPT.filename).suffix == ".md"


def test_candidate_prompt_requires_one_independently_assessable_performance():
    text = (PROMPTS_ROOT / "candidate_formation.md").read_text(encoding="utf-8")

    assert "one independently learnable and assessable performance" in text
    assert "Do not classify content kind or Bloom level" in text
    assert "Do not split\n  inseparable steps" in text
    assert "Associate only supplied source-feature IDs" in text
    assert "workplace framing alone does not make a performance\n  application" in text
    assert "Do not manufacture variants or\n  enforce a distribution quota" in text
    assert "blueprint\n  importance as advisory" in text
    assert "An umbrella verb does not make bundled performances atomic" in text
    assert "one assessment can demonstrate the complete performance" in text
    assert "Do not bundle performances to improve curriculum" in text
    assert "precise fact retrieval" in text
    assert "This is a formation constraint, not a request to classify" in text
    assert objectives.PROPOSAL_PROMPT.version == "v11"


def test_curriculum_prompts_keep_coverage_advisory_and_gap_discovery_bounded():
    blueprint = (PROMPTS_ROOT / "document_curriculum_blueprint.md").read_text(
        encoding="utf-8"
    )
    coverage = (PROMPTS_ROOT / "objective_set_coverage_review.md").read_text(
        encoding="utf-8"
    )
    gap = (PROMPTS_ROOT / "coverage_gap_discovery.md").read_text(encoding="utf-8")
    alignment = (PROMPTS_ROOT / "gap_target_alignment.md").read_text(
        encoding="utf-8"
    )

    assert "Treat importance as an advisory judgment" in blueprint
    assert "source_insufficient" in coverage
    assert "one-objective-per-domain quota" in coverage
    assert "one named\nmissing-performance target" in gap
    assert "Do not manufacture an objective" in gap
    assert "Do not use an umbrella verb to combine them" in gap
    assert "Do not bundle distinct performances" in gap
    assert "Each gap target must express one independently learnable" in coverage
    assert "Adequate domains must return no gap targets" in coverage
    assert "supporting a target does not by itself resolve" in coverage
    assert "Accept defensible paraphrase and instructional transformation" in alignment
    assert "Do not require exact\n  source wording" in alignment
    assert objectives.COVERAGE_PROMPT.version == "v4"
    assert objectives.GAP_PROMPT.version == "v6"
    assert objectives.TARGET_ALIGNMENT_PROMPT.version == "v1"


def test_shared_rules_are_composed_into_discovery_and_classification_prompts():
    assert "D-12:" in objectives.SIGNAL_PROMPT.text
    assert "D-16:" in objectives.PROPOSAL_PROMPT.text
    assert "C-10:" in objectives.CLASSIFICATION_PROMPT.text
    assert "C-10:" in objectives.CLASSIFICATION_REPAIR_PROMPT.text
    assert "Combined confidence is the lower" in objectives.CLASSIFICATION_PROMPT.text
    assert "The only supported POC2 cells" in objectives.CLASSIFICATION_PROMPT.text
    assert "not a request to classify" in objectives.PROPOSAL_PROMPT.text

    excluded_cells = (
        "Fact × Understand",
        "Concept × Analyze",
        "Process × Apply",
        "Process × Analyze",
        "Procedure × Analyze",
        "Principle × Apply",
        "Principle × Analyze",
        "Principle × Evaluate",
    )
    assert all(
        cell not in objectives.CLASSIFICATION_PROMPT.text
        for cell in excluded_cells
    )


def test_objective_classification_does_not_infer_apply_from_workplace_context():
    text = (PROMPTS_ROOT / "objective_classification.md").read_text(encoding="utf-8")

    assert "workplace framing alone does not establish Apply" in text
    assert "Explanation or interpretation without case application is Understand" in text
    assert "lowest cognitive\n  level unambiguously required" in text
    assert "Do not force a balanced distribution" in text


def test_practitioner_lens_prompt_considers_deloitte_role_variety_without_quotas():
    text = (PROMPTS_ROOT / "practitioner_lenses.md").read_text(encoding="utf-8")

    assert "Tax, Audit & Assurance, and Consulting" in text
    assert "varied specialties" in text
    assert "Do not manufacture\n  lenses merely to represent every business" in text


def test_prompt_hash_changes_when_source_text_changes(tmp_path, monkeypatch):
    path = tmp_path / "test.md"
    path.write_text("Prompt ID: `test`\nPrompt Version: `v1`\nFirst", encoding="utf-8")
    monkeypatch.setattr(prompt_assets, "PROMPTS_ROOT", tmp_path)
    first = prompt_assets.load_prompt_asset("test.md", prompt_id="test", version="v1")

    path.write_text("Prompt ID: `test`\nPrompt Version: `v1`\nSecond", encoding="utf-8")
    second = prompt_assets.load_prompt_asset("test.md", prompt_id="test", version="v1")

    assert first.sha256 != second.sha256
