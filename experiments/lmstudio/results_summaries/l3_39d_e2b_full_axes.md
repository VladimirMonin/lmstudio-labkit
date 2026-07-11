# L3.39d Gemma 4 E2B full-axes result

Status: terminal under the reviewed stop gates.

Exact model: `google/gemma-4-e2b@q4_k_m`.

## Result

The 23-cell E2B matrix is fully reconciled: 4 new text calls, 6 exact-match vision calls reused from the independently reviewed L3.39a evidence, and 13 zero-call cells with explicit reasons. All new calls were serial, privately captured outside the repository, read directly, unloaded after each request, and ended with global loaded count zero.

### Text structured output

- Simple/off and simple/on were correct and schema-valid after the permitted single-fence normalization. Raw output was fenced rather than strict JSON.
- Blocks/off and blocks/on preserved the three ordered concepts, but both returned a top-level array instead of the required object containing `blocks`; the off row also used `block_id`. Both therefore failed the fixed schema gate.
- Complex/off and complex/on were not called after their respective blocks failures.
- Reasoning/on produced correct simple output but did not rescue the blocks contract; it added 324 and 404 reasoning tokens in the two executed rows.

### Image structured output

The exact E2B rows from L3.39a were reused because model variant, native route, PNG identity, prompts, output caps, reasoning modes, and rubric match this matrix. Both perception rows and both simple structured rows were accepted. Both medium rows were grounded but schema-invalid, so both complex rows remained zero-call. No duplicate image inference was performed.

### Context and loaded-session processing

The one-shot 4k/12k/28k rows were not called. The reviewed runner requires an external exact per-row tokenizer count map before model load; no such map exists, and approximate counts would violate the token-fit gate. Consequently the six session rows were also zero-call because the required accepted 16k context prerequisite was unavailable.

## Safety and limitations

- New live calls: 4; reused reviewed vision calls: 6; zero-call cells: 13.
- No retries, downloads, parallel inference, commit, or push.
- Raw messages and reasoning remain external to Git.
- Final LM Studio global loaded count: 0; cleanup incidents: 0.
- No claim is made for complex text/vision, one-shot context scaling, loaded-session behavior, cache benefit, KV reuse, or memory attribution.
