"""Render every component archetype without an LLM call."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from renderer import render_course_html
from schema import CourseContent


def _base(screen_id: str, sequence: int, screen_type: str) -> dict:
    return {
        "screen_id": screen_id,
        "sequence": sequence,
        "type": screen_type,
        "rlo_source_refs": ["concepts[0]"],
        "image_prompt": None,
        "image_path": None,
    }


def gallery_course(theme: str) -> CourseContent:
    screens = [
        {**_base("title", 1, "title"), "course_title": "Component Gallery", "subtitle": "A deterministic preview of reusable learning layouts.", "hook": "How can one content contract support many instructional purposes?", "metadata": {"firm": "Deloitte", "level": "introductory", "duration_minutes": 10}},
        {**_base("objectives", 2, "objectives"), "heading": "What You Will See", "objectives": ["Review reusable layouts", "Check interactions and density"]},
        {**_base("flip", 3, "concept_flip_card"), "section_label": "Related Concepts", "instruction": "Activate each card to reveal its explanation.", "cards": [{"id": "c1", "front_label": "Signal", "front_teaser": "An observable indication", "back_definition": "A signal is evidence that helps a learner recognize a condition.", "back_examples": ["A visible change in state"], "back_safeguard": "Interpret signals in context."}, {"id": "c2", "front_label": "Response", "front_teaser": "An action following a signal", "back_definition": "A response is an action selected after interpreting available evidence.", "back_examples": ["Choosing the next step"], "back_safeguard": "Confirm the evidence first."}]},
        {**_base("worked", 4, "worked_example"), "title": "Worked Application", "scenario": "A learner encounters an unfamiliar condition.", "analysis": "They compare the evidence with the governing rule.", "resolution": "They select the response supported by that rule.", "lesson": "Use evidence before choosing an action."},
        {**_base("contrast", 5, "contrast_example"), "title": "Two Approaches", "acceptable": {"label": "Evidence-led", "description": "Review the available evidence before acting.", "reason": "The decision remains traceable."}, "unacceptable": {"label": "Assumption-led", "description": "Act before checking the available evidence.", "reason": "The decision may rest on a false premise."}},
        {**_base("scenario", 6, "scenario_setup"), "title": "Choose a Response", "setup_text": "A new situation presents incomplete information and a time-sensitive choice.", "prompt": "What should you do first?", "branches": [{"id": "branch-a", "label": "Check the strongest available evidence"}, {"id": "branch-b", "label": "Act on the first assumption"}]},
        {**_base("branch-a", 7, "scenario_branch"), "branch_id": "branch-a", "outcome_type": "correct", "feedback_title": "Evidence First", "feedback_body": "Checking evidence reduces avoidable error and makes the choice explainable.", "resolution_screen_id": "resolution"},
        {**_base("branch-b", 8, "scenario_branch"), "branch_id": "branch-b", "outcome_type": "incorrect", "feedback_title": "Reconsider", "feedback_body": "An unchecked assumption can direct the response toward the wrong problem.", "resolution_screen_id": "resolution"},
        {**_base("resolution", 9, "scenario_resolution"), "title": "What This Demonstrates", "body": "Reliable decisions connect observable evidence, an applicable rule, and a proportionate response."},
        {**_base("process", 10, "process_sequence"), "heading": "A Repeatable Process", "introduction": "Move from observation to action through a small set of explicit steps.", "steps": [{"label": "Observe", "detail": "Collect relevant evidence."}, {"label": "Interpret", "detail": "Compare evidence with the rule."}, {"label": "Decide", "detail": "Select a supported response."}, {"label": "Review", "detail": "Check the resulting outcome."}]},
        {**_base("myths", 11, "misconception_buster"), "heading": "Correct the Mental Model", "pairs": [{"claim": "The first explanation is usually sufficient.", "correction": "A plausible explanation still needs evidence before it can support action."}, {"claim": "More information always improves a decision.", "correction": "Relevant information improves a decision; unrelated detail can obscure the signal."}]},
        {**_base("comparison", 12, "comparison_table"), "heading": "Compare the Options", "columns": ["Option A", "Option B"], "rows": [{"label": "Evidence", "values": ["Explicitly checked", "Assumed"]}, {"label": "Traceability", "values": ["Clear rationale", "Unclear rationale"]}]},
        {**_base("tabs", 13, "tabbed_content"), "heading": "Explore the Elements", "instruction": "Use the tabs to review each peer category.", "tabs": [{"label": "Evidence", "heading": "What is known", "body": "Evidence is the observable information available for interpretation."}, {"label": "Rule", "heading": "What governs", "body": "A rule explains how relevant evidence should influence the decision."}, {"label": "Response", "heading": "What follows", "body": "A response is the action supported by the evidence and rule."}]},
        {**_base("rule", 14, "rule_card"), "heading": "The Governing Principle", "principle": "Make the smallest decision that the available evidence can support.", "supporting_detail": "This keeps the response proportionate and makes uncertainty visible instead of hiding it behind confidence.", "examples": ["Pause when a critical fact is missing", "Record the evidence used"]},
        {**_base("reflection", 15, "reflection_prompt"), "heading": "Apply It to Your Context", "prompt": "Where might an unchecked assumption influence a decision you make regularly?", "guidance": "Identify the evidence that would confirm or challenge that assumption."},
        {**_base("takeaways", 16, "key_takeaways"), "heading": "Key Takeaways", "takeaways": ["Separate observations from assumptions.", "Connect each response to a governing rule.", "Keep actions proportionate to available evidence.", "Review outcomes and adjust."]},
        {**_base("check", 17, "knowledge_check"), "question_id": "q1", "stem": "Which action best supports a traceable decision?", "question_type": "multiple_choice_single", "options": [{"id": "a", "text": "Check relevant evidence before acting", "correct": True, "feedback": "Correct. The evidence provides a defensible basis for the response."}, {"id": "b", "text": "Act on the first plausible assumption", "correct": False, "feedback": "A plausible assumption is not yet evidence and may frame the problem incorrectly."}]},
        {**_base("video", 18, "video_player"), "title": "Media Player", "video_src": "assets/gallery-video-placeholder.mp4", "poster_path": None, "captions_path": None},
        {**_base("cards", 19, "card_grid"), "layout_variant": "icon_cards", "heading": "Three Related Ideas", "introduction": "All three peer concepts remain visible together; no activation is required.", "cards": [{"icon": "◎", "eyebrow": "Observe", "heading": "Notice the signal", "body": "Identify the evidence relevant to the decision."}, {"icon": "◇", "eyebrow": "Interpret", "heading": "Apply the rule", "body": "Connect the evidence to its governing principle."}, {"icon": "→", "eyebrow": "Respond", "heading": "Choose an action", "body": "Take a proportionate and traceable next step."}]},
        {**_base("callout", 20, "callout_focus"), "layout_variant": "key_stat", "eyebrow": "Key measure", "headline": "3 decisions", "body": "Observe, interpret, and respond form the core decision pattern.", "attribution": None},
        {**_base("checklist", 21, "structured_list"), "layout_variant": "checklist", "heading": "Before You Act", "introduction": "Use this practical checklist to make the decision traceable.", "items": [{"label": "Evidence", "detail": "Confirm the relevant evidence."}, {"label": "Rule", "detail": "Identify the governing principle."}, {"label": "Response", "detail": "Choose a proportionate action."}, {"label": "Review", "detail": "Check the result and adjust."}]},
        {**_base("paired", 22, "paired_comparison"), "layout_variant": "before_after", "heading": "Compare Two States", "introduction": "Exactly two corresponding states remain visible together.", "left": {"label": "Before", "summary": "Reasoning is implicit.", "points": ["Evidence varies", "Review is difficult"]}, "right": {"label": "After", "summary": "Reasoning is explicit.", "points": ["Evidence is recorded", "Review is repeatable"]}},
        {**_base("disclosure", 23, "disclosure_list"), "layout_variant": "faq", "heading": "Explore Common Questions", "instruction": "Open a question to inspect its answer.", "items": [{"label": "What should be recorded?", "heading": "Relevant evidence", "body": "Record the evidence, governing rule, selected response, and material uncertainty."}, {"label": "When should it be reviewed?", "heading": "At a meaningful trigger", "body": "Review when new evidence appears or the observed outcome differs from expectations."}]},
        {**_base("relationship", 24, "relationship_diagram"), "layout_variant": "continuum", "heading": "Show Difference by Degree", "introduction": "Items occupy a supplied scale rather than unrelated categories.", "x_axis_label": "Lower to higher commitment", "nodes": [{"id": "record", "label": "Record", "detail": "Preserve the observation."}, {"id": "verify", "label": "Verify", "detail": "Seek confirmation."}, {"id": "adjust", "label": "Adjust", "detail": "Change the response."}]},
        {**_base("completion", 25, "completion"), "heading": "Gallery Complete", "message": "Every registered archetype rendered from deterministic presentation data.", "skills_reinforced": ["Layout review", "Interaction review", "Density review"]},
    ]
    return CourseContent(
        rlo_id="synthetic-component-gallery",
        rlo_version="1.0.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        theme_id=theme,
        screens=screens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", default="deloitte-green")
    parser.add_argument("--out", default="/generated/component-gallery.html")
    args = parser.parse_args()
    course = gallery_course(args.theme)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_course_html(course, args.theme), encoding="utf-8")
    print(f"Rendered {len(course.screens)} gallery screens → {path}")


if __name__ == "__main__":
    main()
