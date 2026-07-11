# L3.39a E2B/E4B vision results

Status: completed bounded execution and independent private review.

This report covers only the four authorized E2B/E4B vision lanes. It does not make claims about the broader L3.39 family matrix, text quality, context scaling, session reuse, cache behavior, or untested complex vision stages.

## Evidence boundary

The report reconciles the frozen 16-request manifest (`manifest-e72ccadf`), two immutable sanitized phase records (`phase-e2b-20260711` and `phase-e4b-20260711`), and the independently scored private review set (`review-a1e5715e`). Private prompts, responses, reasoning, fixture truth, image content, paths, and expected labels are not reproduced here.

## Coverage and protocol

- Planned: 4 lanes and 16 ordered requests across two exact Q4_K_M variants.
- Executed and independently reviewed: 11/16 requests.
- Not executed because lane stop rules fired: 5/16 requests.
- Models: Gemma 4 E2B and Gemma 4 E4B.
- Reasoning modes: off and on for each model.
- Stages: perception, simple structured, medium structured, and complex structured.
- Output-token caps tested: 1,024, 2,048, 4,096, and 6,144. Planned 8,192-cap requests were stop-gated before execution.
- Runtime contract: serial execution, parallelism 1, cold model instance per lane, retries off, temperature 0, streaming native chat route, fixed prompts, fixed image identity, no downloads, and private capture per executed request.
- Cleanup: every executed or blocked row reports cleanup verified; both model phases ended with a global loaded-model count of zero. No cleanup incident was recorded.

The E2B reasoning-off perception canary was completed and reviewed under the preceding canary authorization, then carried forward without retry. Orders 2–16 ran under the frozen remaining-scope manifest. This is the only execution-sequencing deviation; it preserved the no-retry rule and the combined order set still reconciles to 16 planned rows.

## Validity taxonomy

The following measures are intentionally independent:

- Raw JSON validity: the returned structured message parses directly as JSON without transformation.
- Normalized JSON validity: a structured message parses only after the permitted single-complete-fence unwrap; no semantic repair is allowed.
- Schema validity: the normalized JSON matches the required schema.
- Semantic grounding: the independently reviewed answer is supported by the pinned fixture truth under the fixed rubric. Grounding does not imply schema validity, and syntax/schema validity does not imply grounding.

## Aggregate outcomes

| Measure | Result | Denominator |
| --- | ---: | ---: |
| Requests executed and reviewed | 11 | 16 planned |
| Requests stop-gated without a call | 5 | 16 planned |
| Perception grounding valid | 3 | 4 perception rows |
| All-row semantic grounding valid | 9 | 11 executed rows |
| Raw JSON valid | 0 | 7 structured rows |
| Normalized JSON valid | 7 | 7 structured rows |
| Schema valid | 3 | 7 structured rows |
| Final rubric verdict accepted | 5 | 11 executed rows |

All seven structured outputs required the same permitted fence-only normalization. Therefore, normalized syntax success must not be reported as direct JSON compliance. Four normalized documents still failed their schemas. Two executed rows were semantically ungrounded even though one of them was normalized-JSON-valid and schema-valid.

## Per-lane outcomes

| Lane | Executed / planned | Grounding valid | Raw JSON valid | Normalized JSON valid | Schema valid | Rubric accepted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| E2B, reasoning off | 3 / 4 | 3 / 3 | 0 / 2 | 2 / 2 | 1 / 2 | 2 / 3 |
| E2B, reasoning on | 3 / 4 | 3 / 3 | 0 / 2 | 2 / 2 | 1 / 2 | 2 / 3 |
| E4B, reasoning off | 3 / 4 | 1 / 3 | 0 / 2 | 2 / 2 | 1 / 2 | 0 / 3 |
| E4B, reasoning on | 2 / 4 | 2 / 2 | 0 / 1 | 1 / 1 | 0 / 1 | 1 / 2 |

The independent review supersedes provisional execution-time business verdicts for semantic claims. In particular, E4B reasoning-off produced transport-successful outputs, but only one of its three executed rows met the final grounding criterion.

## Blocked rows and stop rules

- E2B, reasoning off: complex was not called after the medium structured row failed schema validity.
- E2B, reasoning on: complex was not called after the medium structured row failed the lane gate.
- E4B, reasoning off: complex was not called after the medium structured row failed the lane gate.
- E4B, reasoning on: medium and complex were not called after the simple structured row failed schema validity.

Blocked rows represent zero-call protocol outcomes, not model responses and not quality failures at those unexecuted stages.

## Rubric-qualified findings and limitations

- E2B was grounded on all six executed rows, with both medium structured rows rejected because schema/instruction requirements were not fully met.
- E4B reasoning-off was the weakest reviewed lane: its perception and simple rows contained fixture-truth problems, while its medium row was grounded but schema-invalid.
- E4B reasoning-on perception was accepted and fully grounded; its simple structured row was grounded but incomplete and schema-invalid, which correctly blocked later stages.
- Reasoning content was reviewed for all five executed reasoning-on rows. Some accepted final answers still had rubric deductions for unsupported or incomplete intermediate claims; reasoning-on is therefore not a blanket quality win.
- The sample uses one pinned fixture, one request per executed order, deterministic decoding, and no retries. Results are calibration evidence, not a broad statistical ranking.
- No complex-stage result exists because every complex request was stop-gated. No claim about complex vision capability is supported.
- No cleanup, transport, HTTP, model-substitution, image-identity, or cap-drift incident was recorded in the completed phase summaries.

## Conclusion

The transport and serial lifecycle completed cleanly, but structured compliance remained weak: 7/7 structured messages became syntactically valid only after fence normalization, while only 3/7 met schema requirements. Semantic grounding was stronger overall at 9/11, concentrated in E2B and E4B reasoning-on, but it must remain separate from syntax and schema results. The evidence supports retaining these lanes as bounded calibration results only; it does not support broad family admission or claims for stop-gated complex stages.
