# Adaptive Local Request Product Contract Analysis

Status: ACTIVE PLAN

## Goal

Design an evidence-backed host-product contract for approved local-model recommendation, exact runtime token/context planning, summary-based global context, provider-neutral prompts, structured postprocessing/translation, and separate microphone dictation versus command behavior.

## Boundaries

```text
PRIMARY WORKDIR: repository root
BOARD: lmstudio-labkit
EXTERNAL SOURCE: host-application repository
ACCESS: read-only source/tests/docs
MAY EDIT: this plan; unique Markdown+JSON research reports; one final architecture document
MUST NOT EDIT: host-application source; LabKit runtime code/tests/configs; prompts; model registry data; private artifacts
NO LIVE ACTIONS: no model load/download/inference, no cloud calls, no runtime tokenizer capture, no benchmark rerun
```

## Research tracks

1. Hardware-aware approved-model recommendation across CUDA VRAM+RAM and Apple unified memory.
2. Exact runtime tokenizer, chat-template overhead, context fit, and adaptive output budget.
3. Summary artifact lifecycle and removal/deprecation of full-text-per-chunk context.
4. Provider-neutral prompt and structured response contracts for postprocessing and translation.
5. Separate microphone dictation and `MODEL:` command contracts, including plain response extraction without Markdown-wrapper repair.
6. Cross-track synthesis after all five reports.

## Required distinctions

- static estimate versus exact runtime observation;
- model identity versus approved task profile;
- input token fit versus output reserve;
- schema validity versus semantic/product acceptance;
- summary generation versus summary consumption;
- microphone cleanup output versus model-command answer;
- provider transport differences versus shared prompt/task contract.

## Done conditions

- Five independent report pairs exist and their JSON parses.
- Reports cite executed evidence and current source contracts without publishing private prompt/user content.
- Final synthesis specifies decisions, alternatives, migration order, unresolved gates, and proposed implementation cards without dispatching implementation.
- External host repository remains unmodified.

## Non-goals

- No production code or prompt changes.
- No approval of new models.
- No runtime memory/token measurements.
- No removal of legacy placeholders yet.
- No commit or push.
