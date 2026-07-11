# L3.39h Unsloth Gemma 4 31B IQ3_XXS full-axes result

Status: terminal under the reviewed stop gates.

Exact model: `unsloth/gemma-4-31B-it-GGUF/gemma-4-31B-it-UD-IQ3_XXS.gguf` (model key `gemma-4-31b-it`).

## Result

The 16-cell matrix is fully reconciled: 5 new serial live calls and 11 zero-call cells with explicit reasons. Every new private message and reasoning segment was read against the fixed dataset, image truth, and qualitative rubric. Raw prompts, messages, reasoning, and response envelopes remain outside Git. The model was unloaded after every batch, and both LM Studio model endpoints ended at global loaded count zero.

The exact installed artifact passed identity checks for publisher, architecture, format, size, parameter count, IQ3_XXS quantization, remote device-qualified path, and indexed identifier. The model advertises vision but no reasoning-control contract. All requests therefore omitted the reasoning parameter; no `off`/`on` comparison was attempted.

### Text structured output

- Simple was factually correct and schema-valid after the permitted single-complete-fence normalization. It was not raw JSON.
- Blocks preserved all three source steps and ids in order, but returned a bare array with extra text fields instead of the required `blocks` object. It failed the fixed executable schema.
- Complex was not called after the blocks failure.
- The omitted-control responses exposed 226 and 600 reasoning tokens. These observations do not establish a controllable reasoning mode.

### Image structured output

The pinned RGB PNG transport gate passed. Three vision rows executed and were manually reviewed.

- Perception accurately described the window, navigation, controls, visible values, enabled schema state, warning, actions, and layout. Visible-text recall was complete and no fixture contradiction was found.
- Simple was fully grounded and schema-valid after fence-only normalization.
- Medium remained grounded and preserved the visible control order, but emitted `ordered_controls` instead of the fixed `controls` field. It failed the executable schema.
- Complex remained zero-call after the medium failure.

### Context and loaded-session processing

The one-shot 4k/12k/28k rows were not called. The approved runner requires an external exact per-row tokenizer count map before model load; no such map exists, and approximate counts would violate the token-fit gate. The six loaded-session rows were consequently zero-call because the required accepted 16k one-shot context prerequisite was unavailable.

### Comparator observations

- The fenced-JSON regression reproduced across all four executed structured text/image rows. Each required only the permitted single-complete-fence normalization; no semantic repair was applied.
- No reasoning quality comparison is claimed. The installed model exposes reasoning output but advertises no supported reasoning selector, so all `off`/`on` rows remained unsupported zero-call cells.
- Vision transport metadata remained consistent with the final request seam: native `/api/v1/chat`, text then image, pinned 1024×682 RGB PNG.

## Safety and limitations

- New live calls: 5; zero-call cells: 11.
- No retries, downloads, parallel inference, commit, or push.
- Final loaded count: 0 on both `/api/v1/models` and `/api/v0/models`; cleanup incidents: 0.
- No claim is made for reasoning-mode effects, complex text, complex vision, one-shot context scaling, loaded-session behavior, cache benefit, KV reuse, or memory attribution.
