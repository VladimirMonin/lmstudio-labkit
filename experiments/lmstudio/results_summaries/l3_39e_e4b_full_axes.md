# L3.39e Gemma 4 E4B full-axes result

Status: terminal under the reviewed stop gates.

Exact model: `google/gemma-4-e4b@q4_k_m`.

## Result

The 23-cell E4B matrix is fully reconciled: 4 new serial text calls, 5 exact-match vision calls reused from the independently reviewed L3.39a evidence, and 14 zero-call cells with explicit reasons. Every new answer and reasoning segment was read from the external private pack. The model was unloaded after every request, and both LM Studio model endpoints ended at global loaded count zero.

### Text structured output

- Simple/off and simple/on were semantically correct and schema-valid after the permitted single-complete-fence normalization. Neither was raw JSON.
- Blocks/off preserved the three ordered concepts but returned a top-level array with string IDs and extra text fields, so it failed the fixed object schema.
- Blocks/on returned the correct object and ordered integer IDs, but added `content` fields forbidden by the exact schema. It therefore also failed the gate despite being semantically correct.
- Complex/off and complex/on were not called after their respective blocks failures.
- Reasoning/on added 344 tokens to simple and 312 to blocks. It improved the blocks shape but did not achieve the exact schema, so it did not rescue the lane.

### Image structured output

The exact E4B rows from L3.39a were reused because model variant, native route, pinned PNG identity, prompts, output caps, reasoning modes, and rubric match this matrix. No duplicate image inference was performed.

- Reasoning/off executed perception, simple, and medium. Perception and simple had fixture-grounding problems; medium was grounded but schema-invalid. Complex remained zero-call.
- Reasoning/on perception was accepted and grounded. Simple was grounded but incomplete/schema-invalid, which blocked medium and complex.
- Across E4B vision, 5 rows were executed and independently reviewed, 3 rows were stop-gated, and only the reasoning/on perception row received the final accepted rubric verdict.

### Context and loaded-session processing

The one-shot 4k/12k/28k rows were not called. The approved runner requires an external exact per-row tokenizer count map before model load; no such map exists, and approximate counts would violate the token-fit gate. The six session rows were consequently zero-call because the required accepted 16k context prerequisite was unavailable.

## Safety and limitations

- New live calls: 4; reused reviewed vision calls: 5; zero-call cells: 14.
- No retries, downloads, parallel inference, commit, or push.
- Raw prompts, messages, reasoning, and full envelopes remain outside Git under the private evidence boundary.
- Final LM Studio loaded count: 0 on both `/api/v1/models` and `/api/v0/models`; cleanup incidents: 0.
- No claim is made for complex text, broad E4B vision admission, complex vision, one-shot context scaling, loaded-session behavior, cache benefit, KV reuse, or memory attribution.
