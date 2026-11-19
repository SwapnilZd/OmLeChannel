# Token and Variable-Cost Forecasting

## Purpose

The most useful way to forecast this platform is in stable units of work rather than the price of one model or the results from one document. Model prices can change, but pages processed, RLOs authored, screens created, and media minutes produced remain understandable planning units.

The figures below are working estimates based on observed POC runs. They are intended for directional budgeting, not as guaranteed limits.

## Source-to-RLO authoring

For an input document with **P pages** and **R reviewable RLOs**:

| Activity | Input tokens | Output tokens | Total tokens |
|---|---:|---:|---:|
| Source processing and objective identification | 19,100 per page | 4,500 per page | 23,600 per page |
| RLO authoring | 458,000 per RLO | 22,000 per RLO | 480,000 per RLO |

The formulas are:

```text
Input tokens  = (19,100 × P) + (458,000 × R)
Output tokens = (4,500 × P) + (22,000 × R)
```

For planning purposes, the simpler total-token formula is:

```text
Total tokens = (23,600 × P) + (480,000 × R)
```

The 480,000-token RLO allowance includes the failure and retry overhead observed during the POC.

The main takeaway is that document processing matters, but RLO authoring is the larger token consumer. Page count is therefore useful for estimating intake and objective creation, while the number of RLOs is the stronger driver of total model usage.

## Content generation

For downstream e-learning generation, the working forecast is:

| Unit | Token allowance |
|---|---:|
| Each RLO selected and planned | 65,000 tokens |
| Each e-learning screen authored and reviewed | 4,000 tokens |
| Each Manim clip designed and coded | 15,000 tokens |
| Each narrated Manim minute | 15,000 speech tokens |

For **R RLOs**, **S screens**, **M Manim clips**, and **A narrated Manim minutes**:

```text
Total tokens = (65,000 × R)
             + (4,000 × S)
             + (15,000 × M)
             + (15,000 × A)
```

Manim uses two drivers. The number of clips drives planning, authoring, and production tokens. Finished duration drives narration tokens. The calculator combines these into one Manim line while retaining both inputs.

### Podcast generation

A podcast uses the same RLO selection and planning allowance as other generated assets, then adds Gemini TTS usage based on finished duration:

```text
Podcast tokens = (65,000 × RLOs used)
               + (15,000 speech tokens × finished minutes)
```

The calculator prices podcast planning with the selected input and output model rates. It prices speech synthesis separately using the configured Gemini 3.1 Flash TTS output rate of $20 per million tokens. At 15,000 speech tokens per finished minute, the TTS portion is approximately $0.30 per minute. The high-level forecast excludes the comparatively small TTS text-input component.

## Planning assumptions

The worked example uses the following assumptions. Most volume and design assumptions can be changed directly in the calculator.

| Area | Working assumption |
|---|---|
| Model usage | Token allowances are based primarily on observed OpenAI-model usage during the POC |
| Source portfolio | 1,000 input pages and 200 approved RLOs |
| E-learning volume | 100 modules |
| RLO density | Two RLOs per module |
| Screen density | 10 base screens per RLO with a 1.0 uplift factor, producing 20 screens per module |
| Manim | Four narrated clips per module, averaging 2.5 minutes each |
| HeyGen | Four finished minutes per module |
| Podcast unit example | Two RLOs and 10 finished minutes per podcast |
| Planning and authoring model pricing | $2 per million input tokens and $10 per million output tokens |
| Gemini TTS pricing | $20 per million speech-output tokens |
| HeyGen pricing | $1 per finished minute |

The observed token allowances are working coefficients rather than model-independent limits. The calculator allows the portfolio volumes, module design, media duration, and pricing rates to be adjusted. A different model mix should be calibrated against its own token telemetry, particularly for reasoning and speech usage.

## Worked portfolio example

Applying these assumptions produces the following directional portfolio estimate.

### Source-to-RLO authoring

```text
Source processing = 1,000 pages × 23,600 tokens = 23,600,000 tokens
RLO authoring      = 200 RLOs × 480,000 tokens = 96,000,000 tokens
Authoring total                                   119,600,000 tokens
```

### E-learning generation

| Component | Calculation | Tokens |
|---|---:|---:|
| RLO selection and planning | 200 × 65,000 | 13,000,000 |
| Screen authoring and review | 2,000 × 4,000 | 8,000,000 |
| Manim clip generation | 400 × 15,000 | 6,000,000 |
| Manim narration | 1,000 minutes × 15,000 | 15,000,000 |
| **Generation total** |  | **42,000,000** |

HeyGen remains separate:

```text
100 e-learnings × 4 HeyGen minutes × $1.00 = $400
```

### Portfolio total

| Model and speech tokens | HeyGen |
|---:|---:|
| 161,600,000 | $400 |

The token total can be priced against any proposed model mix using the input, output, and speech rates in the next section. It does not include infrastructure or human review.

## Portfolio pricing example

Using the GPT-6.1 Sol rates of **$2 per million input tokens** and **$10 per million output tokens**, the portfolio example can be translated into a directional cost estimate. Speech tokens are treated as output tokens for this high-level calculation.

The cost pools should be kept separate. Source ingestion and RLO authoring determine the cost to produce governed RLOs. E-learning and podcast generation are downstream costs that depend on how many assets are requested and should not increase the reported cost per RLO produced.

| Cost pool | Input tokens | Output or speech tokens | Model cost | Other variable cost | Total |
|---|---:|---:|---:|---:|---:|
| Source-to-RLO | 110.7 million | 8.9 million | $310.40 | — | $310.40 |
| E-learning generation | 23.2 million | 18.8 million | $234.40 | $400 HeyGen | $634.40 |
| **Portfolio total** | **133.9 million** | **27.7 million** | **$544.80** | **$400** | **$944.80** |

This produces two different unit costs:

```text
Source-to-RLO cost per RLO = $310.40 ÷ 200 RLOs = $1.55
E-learning cost per module = $634.40 ÷ 100 modules = $6.34
```

### Podcast unit example

For one 10-minute podcast using two RLOs:

| Component | Calculation | Cost |
|---|---:|---:|
| RLO selection and planning | Two RLOs using the 65,000-token planning allowance | $0.38 |
| Gemini TTS | 10 minutes × 15,000 tokens × $20 per million | $3.00 |
| **Total per podcast** |  | **$3.38** |

The calculator allows podcast volume, RLOs per podcast, finished duration, and the Gemini TTS rate to be changed independently.

These rates are deliberately conservative because they price the portfolio as though flagship-model rates apply throughout. The platform's purpose-specific LiteLLM aliases allow individual functions to use lower-tier models where quality permits, which should reduce the actual model cost without changing the forecast units.

## Converting tokens into model cost

Input, output, and speech tokens should remain separate because providers may price them differently:

```text
Model cost = (input tokens ÷ 1,000,000 × input rate)
           + (output tokens ÷ 1,000,000 × output rate)
           + (speech tokens ÷ 1,000,000 × speech rate)
```

This allows the same forecast to be evaluated against different models without rewriting the operating assumptions.

Reasoning-token behavior also varies by model. Some models, including certain Gemini configurations, may use materially more reasoning tokens than the models represented in the POC data. Those tokens may increase the provider-reported output usage and should be included when calibrating the output allowance and pricing a different model mix.

## Other variable consumers

The formulas cover the primary measured path, but actual use can increase because of:

- Failed structured outputs and automatic retries
- RLO or course revision requests
- Grounding, pedagogy, and semantic review calls
- Manim repair attempts after validation or rendering failures
- Embeddings for source segments and published RLOs
- Model-generated explanations of figures and diagrams
- Longer prompts caused by larger source selections or multi-RLO courses
- Repeated generation when an otherwise valid output is rejected for quality reasons

## Non-token costs

HeyGen is the main generation cost that should remain outside the token formula. The current working rate is:

```text
HeyGen cost = $1.00 × finished HeyGen minutes
```

The estimates in this document do not include infrastructure, storage, network transfer, database services, monitoring, backup, support, or human review. CPU or GPU time for Docling extraction and Manim rendering should also be treated as infrastructure consumption rather than model-token usage.

## Recommended forecasting approach

For early planning, use the rounded formulas above. As production data grows, the same units should be tracked as distributions rather than replaced with one overall average: tokens per page, tokens per approved RLO, tokens per screen, tokens per media clip, and tokens per finished media minute.
