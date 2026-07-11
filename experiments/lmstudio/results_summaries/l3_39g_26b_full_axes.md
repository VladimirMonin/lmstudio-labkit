# L3.39g Gemma 4 26B-A4B QAT full-axes result

Status: terminal under the reviewed stop gates.

Exact model: `google/gemma-4-26b-a4b-qat@q4_0`.

## Result

The 23-cell matrix is fully reconciled: 10 new serial live calls and 13 zero-call cells with explicit reasons. Every new private message and available reasoning segment was read against the fixed dataset, image truth, and qualitative rubric. Raw prompts, messages, reasoning, and response envelopes remain outside Git. The model was unloaded after every batch, and both LM Studio model endpoints ended at global loaded count zero.

### Text structured output

- Simple/off and simple/on were factually correct and schema-valid after the permitted single-complete-fence normalization. Neither was raw JSON.
- Blocks/off and blocks/on preserved all three source steps in order but returned numeric object keys instead of the required `blocks` array. Both failed the fixed executable schema.
- Complex/off and complex/on were not called after their respective blocks failures.
- Reasoning/on added 363 tokens to simple and 947 to blocks. It produced the same simple answer and explicitly considered but rejected the correct array form for blocks, so it provided no quality benefit for these exact rows.

### Image structured output

The pinned RGB PNG transport gate passed. Six vision rows executed and were manually reviewed.

- Perception/off and perception/on accurately described the window, navigation, controls, visible values, enabled schema state, warning, and actions. Both were grounded with no fixture contradiction.
- Simple/off and simple/on were fully grounded and schema-valid after fence-only normalization.
- Medium/off and medium/on remained grounded, but both emitted an alternate ordered-controls key instead of the fixed `controls` field. They failed the executable schema.
- Complex/off and complex/on remained zero-call after the medium failures.
- Reasoning/on added 894–2125 reasoning tokens across the executed vision rows without improving the accepted results or rescuing the medium schema.

### Context and loaded-session processing

The one-shot 4k/12k/28k rows were not called. The approved runner requires an external exact per-row tokenizer count map before model load; no such map exists, and approximate counts would violate the token-fit gate. The six loaded-session rows were consequently zero-call because the required accepted 16k one-shot context prerequisite was unavailable.

### Comparator observations

- The fenced-JSON regression reproduced across all eight executed structured text/image rows. Each required only the permitted single-complete-fence normalization; no semantic repair was applied.
- For the exact paired rows that passed, reasoning off delivered equivalent reviewed quality with fewer tokens. This is a model × task × route × context result, not a family-wide reasoning claim.
- Vision transport metadata remained consistent with the final request seam: native `/api/v1/chat`, text then image, pinned 1024×682 RGB PNG.

## Safety and limitations

- New live calls: 10; zero-call cells: 13.
- No retries, downloads, parallel inference, commit, or push.
- Final loaded count: 0 on both `/api/v1/models` and `/api/v0/models`; cleanup incidents: 0.
- No claim is made for complex text, complex vision, one-shot context scaling, loaded-session behavior, cache benefit, KV reuse, or memory attribution.
