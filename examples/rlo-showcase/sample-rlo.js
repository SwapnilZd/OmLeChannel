window.SAMPLE_RLO = {
  id: "rlo-cand-gap-risk-prioritization-for-management-effort",
  displayTitle: "Prioritize AI risks for management effort",
  title: "prioritize mapped and measured AI risks for allocation of policies, resources, and management effort according to assessed risk, potential impact, and context",
  topic: "Prioritization of supplied risks using assessed risk, potential impact, and context as stated criteria.",
  audience: ["Deloitte practitioners"],
  duration: 30,
  content_type: "procedure",
  performance_level: "apply",
  enabling_objective: {
    statement: "The learner will be able to prioritize mapped and measured AI risks for allocation of policies, resources, and management effort according to assessed risk, potential impact, and context."
  },
  components: [
    {
      id: "comp-setup-001",
      type: "hook",
      title: "A prioritization decision is waiting",
      content: {
        origin: "source",
        content: "## A prioritization decision is waiting\n\nA team has completed its AI-risk assessment and needs to decide where to focus management attention first. Its risk register contains several mapped and measured risks with different assessed-risk levels, potential impacts, and use contexts. The team needs a defensible **relative priority order** before it can direct policies, resources, and management effort.\n\nIn this lesson, you will work from the supplied evidence—not create risk thresholds, choose treatments, or assign resource amounts."
      }
    },
    {
      id: "comp-setup-002",
      type: "rule",
      title: "Your objective",
      content: {
        origin: "mixed",
        content: "## Your objective\n\nGiven mapped and measured AI risks with stated assessed risk, potential impact, and context, **prioritize the risks for allocation of policies, resources, and management effort**. Your priority order will state the relative basis for each ordering decision."
      }
    },
    {
      id: "comp-setup-003",
      type: "recall_prompt",
      title: "Before you begin",
      content: {
        origin: "source",
        content: "## Before you begin\n\nYou will need to recognize the information already supplied for each risk:\n\n- its assessed-risk level;\n- its potential impact; and\n- its contextual information.\n\nThese inputs come from earlier mapping and measurement work. This lesson begins once that information is available."
      }
    },
    {
      id: "comp-teach-004",
      type: "rule",
      title: "Prioritize assessed risks",
      content: {
        origin: "mixed",
        content: "## Prioritize assessed risks to focus management effort\n\nUse prioritization after risks have been mapped and measured. MAP establishes the context for AI-system risks, and MEASURE assesses AI risks and related impacts. Their assessment and analytical output informs MANAGE. In MANAGE, organizations allocate risk resources to mapped and measured risks regularly, as defined by GOVERN. The point is not to eliminate every negative risk. It is to direct policies, resources, and management effort purposefully toward the risks that warrant the most attention.\n\nA priority ordering is relative: it shows which supplied risks should receive more urgent and thorough risk-management attention than others. For a given context of use, risks determined to be highest call for the most urgent prioritization and the most thorough risk-management process. Risks found to be low risk in their specific context may warrant lower priority.\n\n## Use a consistent ordering rule\n\n**Entry condition:** You have a set of mapped and measured risks. For each risk, the scenario supplies an assessed-risk level, potential impact, and contextual information. It does not ask you to set risk tolerance, select a treatment, decide whether deployment should cease, or assign resource amounts.\n\nWhen the scenario provides no governance-directed weighting or scoring formula, apply this transparent default:\n\n1. **Normalize the supplied information.** Put each risk's assessed-risk level, potential impact, and contextual facts into the same relative categories used in the scenario. Compare like with like. Do not create new thresholds or scores.\n2. **Order by assessed-risk level first.** Place risks with the higher supplied assessed-risk level ahead of those with a lower level.\n3. **Use potential impact to resolve ties.** When two or more risks have the same assessed-risk level, place the risk with the greater supplied potential impact ahead.\n4. **Use a scenario-stated context rule to resolve remaining ties.** Apply context only when assessed-risk level and potential impact do not distinguish the risks. The scenario must explicitly state how its contextual facts rank the tied risks, such as labeling one context as higher relative consequence for the tie-break. Do not infer that a particular contextual factor always outranks another. Human interaction, sensitive or protected data, and tailoring to a context of use may be relevant, but their precedence depends on the facts and rule supplied in the scenario.\n5. **State the basis for every position.** List each risk in priority order and identify whether assessed-risk level, potential impact, or the scenario-stated context rule determined its relative placement.\n\nDo not use this default sequence when a scenario-stated rule, applicable governance direction, or legal obligation gives factors different precedence. Follow that stated direction instead.\n\n## Avoid a common error\n\nDo not rank from just one input. Potential impact and context matter, but under the default rule they do not override a difference in supplied assessed-risk level. Conversely, do not ignore impact or a stated contextual comparison rule when risks are tied at the preceding comparison step.\n\n**Exit condition:** Your output is a complete relative ordering of the supplied risks, with a brief, supplied-factor rationale for each ordering decision. The ordering informs relative management attention and allocation priorities. It does not itself establish risk tolerance, approve a treatment, or set resource amounts."
      }
    },
    {
      id: "comp-teach-005",
      type: "rule",
      title: "Why prioritization matters",
      content: {
        origin: "source",
        content: "Policies and resources should be prioritized based on an AI system's assessed risk level and potential impact; the extent to which the system is tailored to its specific context of use can also contribute to prioritization.\n\nFor AI systems in a given context of use, risks the organization determines are highest call for the most urgent prioritization and the most thorough risk-management process; a system found to be low risk in a specific context may warrant lower prioritization.\n\nTrying to eliminate negative risk entirely can be counterproductive because not all incidents and failures can be eliminated; unrealistic expectations can make risk triage inefficient or impractical or waste scarce resources.\n\nThe MAP function establishes context for AI-system risks, and its outcomes are the basis for the MEASURE and MANAGE functions; the MEASURE function analyzes and assesses AI risks and related impacts using quantitative, qualitative, or mixed-method approaches and informs MANAGE.\n\nThe MANAGE function entails allocating risk resources to mapped and measured risks regularly and as defined by the GOVERN function.\n\nTreatment of documented AI risks is prioritized based on impact, likelihood, and available resources or methods.\n\nAI risks based on assessments and other analytical output from the MAP and MEASURE functions are prioritized, responded to, and managed.\n\nContextual information from expert consultation and relevant AI actors, established in GOVERN and carried out in MAP, is used in MANAGE to decrease the likelihood of system failures and negative impacts.\n\nAfter the MANAGE function, plans for prioritizing risk and regular monitoring and improvement will be in place, enhancing users' capacity to allocate risk-management resources based on assessed and prioritized risks.\n\nIdentifying contextual factors in the MAP function assists AI actors in determining the level of risk and potential management efforts."
      }
    },
    {
      id: "comp-show-006",
      type: "example",
      title: "Worked example",
      content: {
        origin: "mixed",
        content: "## Worked example: Rank three supplied risks\n\nA review team has three mapped and measured risks. The scenario provides the following relative categories and does not provide a weighting formula or a different governance rule.\n\n**Scenario context rule for a remaining tie:** A context labeled **Elevated for this comparison** ranks ahead of a context labeled **Standard for this comparison**. The labels apply only to this scenario's final contextual tie-break.\n\n| Risk | Assessed risk | Potential impact | Supplied context | Context label |\n|---|---|---|---|---|\n| A | High | High | The system uses sensitive data and interacts directly with people. | Elevated for this comparison |\n| B | High | High | The system is used only with computational systems and uses non-sensitive data. | Standard for this comparison |\n| C | Medium | Severe | The system interacts directly with people. | Not needed |\n\n**Decision point:** What order should guide relative management attention?\n\n## 1. Compare assessed-risk levels first\n\nA and B are both assessed **High**. C is assessed **Medium**. Under the default rule, A and B come ahead of C because assessed-risk level is compared first. The severe potential impact for C is not ignored. It would distinguish C from another risk with the same assessed-risk level. It does not override the supplied assessed-risk difference in this scenario.\n\n## 2. Resolve the tie between A and B\n\nA and B remain tied on assessed risk and potential impact. Move to the supplied context rule. The scenario labels A as Elevated for this comparison and B as Standard for this comparison. A therefore receives the higher priority. The priority follows the stated comparison rule, not an assumption that sensitive data or human interaction always takes precedence.\n\n## 3. Record the ordering and its basis\n\n1. **Risk A, highest priority.** It is tied with B on assessed risk and potential impact. The scenario's context label breaks the tie.\n2. **Risk B, next priority.** It has a High assessed-risk level and High potential impact, but the scenario's context rule places it behind A.\n3. **Risk C, lower relative priority.** Its potential impact is Severe, but its assessed-risk level is Medium, below A and B under the stated ordering rule.\n\n## Catch and correct a plausible error\n\nAn initial ordering of C, A, B based only on C's Severe potential impact would skip the assessed-risk comparison. Recheck the rule: assessed risk comes first, then potential impact, then the scenario-stated context rule. Revising the order to A, B, C uses all supplied factors at the appropriate decision point.\n\n**Outcome:** The team now has a transparent priority ordering to inform relative allocation of policies, resources, and management effort. The ordering does not assign amounts or select a risk treatment."
      }
    },
    {
      id: "comp-practice-007",
      type: "multiple_choice_single",
      title: "Practice 1",
      content: {
        stem: "Select the higher-priority risk.",
        options: [
          {
            text: "Risk A, because its context should be considered before potential impact.",
            correct: false,
            feedback: "Risk A's context is relevant only after assessed risk and potential impact fail to distinguish the risks. Here, both risks are assessed High, but Risk B has Severe potential impact compared with Moderate impact for Risk A."
          },
          {
            text: "Risk B, because its greater potential impact resolves the tie at the same assessed-risk level.",
            correct: true,
            feedback: "Correct. The risks are tied at High assessed risk, so compare supplied potential impact next. Risk B's Severe potential impact places it ahead of Risk A. Context is not needed because impact has already distinguished the risks."
          },
          {
            text: "Risk A, because direct interaction with people always overrides the assessed-risk and impact comparison.",
            correct: false,
            feedback: "Direct interaction with people is contextual information that may help resolve a remaining tie. It does not override the supplied potential-impact difference once the risks are tied on assessed-risk level."
          },
          {
            text: "Give both risks equal priority because they have the same assessed-risk level.",
            correct: false,
            feedback: "The same assessed-risk level is the point at which the next comparison is needed. Risk B's greater potential impact resolves the tie, so the risks should not remain equal in the priority ordering."
          }
        ]
      }
    },
    {
      id: "comp-practice-008",
      type: "multiple_choice_single",
      title: "Practice 2",
      content: {
        stem: "## Practice 2: Produce a complete priority order\n\nA review team must order three mapped and measured risks for relative management attention. No governance-directed weighting, scoring formula, or alternative ordering rule is provided.\n\n**Scenario context rule for a remaining tie:** A context labeled **Elevated for this comparison** ranks ahead of a context labeled **Standard for this comparison**. Use these labels only if assessed risk and potential impact do not distinguish the risks.\n\n| Risk | Assessed risk | Potential impact | Context label |\n|---|---|---|---|\n| P | High | High | Standard for this comparison |\n| Q | High | High | Elevated for this comparison |\n| R | Medium | Severe | Not needed |\n\nWhich priority register should guide relative management attention?",
        options: [
          {
            text: "1. R; 2. Q; 3. P. R is first because Severe potential impact outweighs the others' High assessed risk.",
            correct: false,
            feedback: "This ordering starts with potential impact and skips the assessed-risk comparison. Under the default rule, Q and P, both assessed High, come before R, which is assessed Medium."
          },
          {
            text: "1. Q; 2. P; 3. R. Q and P come before R because they are assessed High rather than Medium. Q comes before P because their tied assessed risk and impact are resolved by the scenario's context rule.",
            correct: true,
            feedback: "Correct. Assessed risk places Q and P ahead of R. Q and P are tied on both assessed risk and potential impact, so apply the supplied context rule. Q is labeled Elevated for this comparison and P is labeled Standard for this comparison."
          },
          {
            text: "1. P; 2. Q; 3. R. P and Q come before R because of assessed risk. P comes first because computational-only interaction is more important than Q's context.",
            correct: false,
            feedback: "The first comparison is correct: P and Q are assessed High and precede R. But P and Q remain tied until the scenario's context rule is applied. That rule labels Q as Elevated for this comparison and P as Standard for this comparison."
          },
          {
            text: "1. Q; 2. R; 3. P. Q is first because of context, and R is second because Severe impact always outranks High impact.",
            correct: false,
            feedback: "This combines relevant factors in the wrong sequence. Q and P both have High assessed risk, so both precede R's Medium assessed risk. The scenario's context rule resolves Q and P only after their assessed risk and impact are tied."
          }
        ]
      }
    },
    {
      id: "comp-send-off-009",
      type: "transfer",
      title: "Take it to the risk register",
      content: {
        origin: "mixed",
        content: "## Take it to the risk register\n\nWhen several mapped and measured AI risks compete for management attention, ask: **What supplied factor explains each position in this priority order?**\n\nStart with assessed risk; use potential impact and then context to resolve ties when the scenario provides no different governing rule. Record the basis alongside the order so it can inform relative allocation of policies, resources, and management effort."
      }
    }
  ]
};
