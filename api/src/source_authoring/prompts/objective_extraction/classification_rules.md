# POC2 Content-Kind and Bloom Classification Rules

Prompt ID: `source-objective-classification-rules`

Prompt Version: `v3`

Apply this rubric to Suggested, Target, and Observed classification decisions.

- C-1: Classify the actual learner performance, not a surface verb.
- C-2: Determine content kind first, then Bloom level.
- C-3: Fact × Remember retrieves a precise discrete value, name, citation, threshold,
  date, or assertion without interpretation.
- C-4: Concept depends on definitions, critical attributes, instances, non-instances,
  or category boundaries. Concept × Understand explains or distinguishes the concept
  in familiar terms. Concept × Apply classifies a novel, unambiguous case using its
  deciding attributes.
- C-5: Process × Understand explains or reconstructs a multi-stage flow with actors,
  transitions, handoffs, or dependencies. Mere ordered content is not a Process.
- C-6: Procedure × Apply executes the learner's own steps and decisions in a novel
  standard case, including relevant entry conditions, branches, exit conditions, and
  output.
- C-7: Distinguish a discrete value from attribute-based classification (Fact versus
  Concept), classification from execution (Concept versus Procedure), and a
  multi-actor flow from the learner's own actions (Process versus Procedure).
- C-8: Workplace context or scenario wording alone does not establish Apply. Apply
  requires using supported learning in a concrete new case.
- C-9: Use the minimum cognitive work unambiguously required by the objective,
  evidence, and expected practice. Do not invent practice to justify a higher level.
- C-10: Combined confidence is the lower of content-kind and Bloom confidence.
- C-11: Log verb/practice mismatches and explain which evidence governed.

The only supported POC2 cells are Fact × Remember, Concept × Understand, Concept ×
Apply, Process × Understand, and Procedure × Apply.

If the actual performance instead requires retrieval plus explanation, argumentation,
diagnosis, procedure tailoring, principle-based judgment, evaluation, or another
performance outside those five cells, return `outside_poc2_scope`. Do not force it into
a supported cell. A compound objective should be revised or split upstream rather than
classified by its highest verb.
