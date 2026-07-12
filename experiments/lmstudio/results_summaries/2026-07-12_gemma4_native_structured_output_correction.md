# Gemma 4 native structured-output benchmark correction

## Corrected decision

None of the four tested models is admitted end to end, but the earlier `accepted=0` aggregate must not be read as absence of JSON, schema, or structural capability. The focused native structured-output matrix separates those capabilities instead of collapsing them into one strict verdict.

The historical 80-call report remains unchanged evidence for its original prompt-embedded-schema transport. This addendum supersedes only its admission interpretation.

## Corrected transport and matrix

- Models: the four exact canonical Gemma 4 models; 31B variants excluded.
- Views: M01, M05, and L02-L; one measured attempt per model/view (12 calls).
- Transport: LM Studio Responses API, `/v1/responses`, with `text.format.type=json_schema`, `strict=true`, and the bound JSON schema.
- Reasoning: `reasoning.effort=none`; all 12 envelopes report zero reasoning tokens.
- Sampling: temperature 0, non-streaming, no stored response state.
- Context: 28,672 tokens for every row.
- Output budgets: M01=512, L02-L=512, M05=4,096.
- M05 budget derivation: the retained reference is 1,729 UTF-8 bytes / 1,006 characters; twice the byte size rounded to the next 1,024-token boundary gives 4,096 tokens.
- Raw final text and complete response envelopes are owner-only outside the repository with 0600 files under a 0700 root.
- Every private output was read. All four models were unloaded after their three calls; every post-model read-back and the final read-back reported `loaded_total=0`.

No M05 row hit the output limit. The 4,096-token budget therefore removed output length as an explanation for the corrected M05 results.

## Capability results

Counts are successful rows out of the three focused views per model. Semantic and placeholder fidelity apply to M01/M05; structural retention applies to L02-L.

| Model | Raw JSON | Extracted/fenced JSON | Exact schema | Semantic fidelity | Placeholder fidelity | L02-L retention | Strict accepted |
|---|---:|---:|---:|---:|---:|---:|---:|
| E2B | 2/3 | 3/3 | 3/3 | 0/2 | 0/2 | 0/1 | 0/3 |
| E4B | 0/3 | 2/3 | 2/3 | 0/2 | 0/2 | 0/1 | 0/3 |
| 12B QAT | 0/3 | 3/3 | 2/3 | 0/2 | 0/2 | 1/1 | 0/3 |
| 26B MoE | 0/3 | 3/3 | 1/3 | 0/2 | 0/2 | 0/1 | 0/3 |

### Per-view observations

- M01: E2B produced raw JSON and exact schema; E4B produced fenced but schema-valid JSON; 12B QAT and 26B MoE produced extractable JSON that failed exact schema. No model matched the semantic target or placeholder contract.
- M05: E2B produced raw exact-schema JSON. 12B QAT and 26B MoE produced fenced exact-schema JSON. E4B produced an overlong malformed object despite stopping before the 4,096-token limit. No model matched the reference-relative target or placeholder contract.
- L02-L: 12B QAT reported all 428 units from index 0 through 427 and passed structural retention after fenced extraction. E2B reported 318 units, E4B 43, and 26B MoE 427; none produced raw JSON, so no L02-L row passed strict end-to-end acceptance.

## Comparison with the prior matrix

The strict aggregate remains 0 accepted calls in both reports, but the meaning changes:

- Prior transport: schema embedded only inside the prompt; no native structured-output binding.
- Corrected transport: a native LM Studio JSON-schema field is bound on the wire and reasoning is demonstrably disabled.
- Prior interpretation: JSON/fence/schema/semantic/placeholder/retention failures were folded into one rejection.
- Corrected interpretation: transport and schema capability are present in multiple rows; semantic and placeholder fidelity remain the normalization blockers; 12B QAT demonstrates full L02-L structural retention.

## Updated admission interpretation

- E2B: not admitted, but it is the strongest raw-JSON/schema follower in this focused matrix. Its blocker is semantic and placeholder fidelity, plus incomplete L02-L retention—not basic JSON capability.
- E4B: not admitted. It demonstrates extracted exact-schema capability on two views, but M05 transport output is malformed and semantic/placeholder fidelity fails.
- 12B QAT: not admitted. It is the strongest structural-retention candidate and retains all 428 L02-L units, but fenced transport and normalization fidelity prevent strict acceptance.
- 26B MoE: not admitted. It produces extractable JSON on all views, but exact schema is inconsistent, normalization fidelity fails, and L02-L is short by one retained unit.

No production parallelism or model admission should be inferred from this focused correction. It corrects capability attribution, not the strict operational gate.

## Evidence boundary

Machine-readable companion: `2026-07-12_gemma4_native_structured_output_correction.json`.

The JSON report contains request/schema/raw/envelope digests, timing, usage, finish state, per-axis scores, cleanup read-backs, and the prior-report comparison. It contains no prompts, completions, private paths, credentials, or private raw text.
