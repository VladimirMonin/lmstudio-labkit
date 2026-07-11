# L3.39f Gemma 4 12B QAT full-axes result

Status: terminal under the reviewed stop gates.

Exact model: `google/gemma-4-12b-qat@q4_0`.

## Result

The 23-cell 12B matrix is fully reconciled: 10 new serial live calls and 13 zero-call cells with explicit reasons. I read every new private message and every available reasoning segment against the fixed dataset, fixture truth, and rubric. Raw prompts, messages, reasoning, and response envelopes remain outside Git. The model was unloaded after every batch, and both LM Studio model endpoints ended at global loaded count zero.

### Text structured output

- Simple/off and simple/on were correct and schema-valid after the permitted single-complete-fence normalization. Neither was raw JSON.
- Blocks/off and blocks/on preserved all three source steps in order but returned numeric object keys instead of the fixed `blocks` array. Both therefore failed the executable schema.
- Complex/off and complex/on were not called after their respective blocks failures.
- Reasoning/on added 324 tokens to simple and 295 to blocks without improving the reviewed answer. For these exact rows, reasoning off is the lower-cost equivalent-quality choice.

### Image structured output

The PNG transport gate passed and six 12B vision rows executed under perception-first lane gates.

- Perception/off and perception/on described the layout and most visible text well, but both contradicted the fixture's visible model identifier. Manual rubric review therefore rejects grounding despite the coarse automated recall check passing.
- Simple/off was the only fully accepted vision row: correct visible model identifier, sufficient fixture grounding, and schema validity after fence-only normalization.
- Simple/on was schema-valid after normalization but contradicted the fixture model identifier, so it was rejected on grounding.
- Medium/off was visually grounded, but the response followed the prompt's `ordered_controls` wording while the executable schema requires `controls`. It failed the fixed schema.
- Medium/on had the same schema mismatch and also contradicted the fixture model identifier.
- Complex/off and complex/on remained zero-call after the medium failures.

### Context and loaded-session processing

The one-shot 4k/12k/28k rows were not called. The approved runner requires an external exact per-row tokenizer count map before model load; no such map exists, and approximate counts would violate the token-fit gate. The six loaded-session rows were consequently zero-call because the required accepted 16k one-shot context prerequisite was unavailable.

### Comparator rows

- The known fenced-JSON regression reproduced across all eight executed structured text/image rows. Each required only the permitted single-complete-fence normalization; no semantic repair was applied.
- The earlier reasoning-budget exhaustion pattern did not reproduce at the reviewed 4096/6144 caps. Every reasoning-on row produced a final answer with 295–1823 reasoning tokens. The observed failures were schema or grounding failures, not cap exhaustion.

## Safety and limitations

- New live calls: 10; zero-call cells: 13.
- No retries, downloads, parallel inference, commit, or push.
- Final LM Studio loaded count: 0 on both `/api/v1/models` and `/api/v0/models`; cleanup incidents: 0.
- No claim is made for complex text, broad 12B vision admission, complex vision, one-shot context scaling, loaded-session behavior, cache benefit, KV reuse, or memory attribution.
