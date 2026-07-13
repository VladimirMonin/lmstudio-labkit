# Strict vision 40-call manual reconciliation

Status: **manual pixel/raw reconciliation complete**

This report separates transport, raw JSON, schema validation, visible-text accuracy, object accuracy, unsupported claims, and repeatability. The primary semantic evidence is direct inspection of all four PNG fixtures and all 40 preserved raw responses. Automated counters are reported only as separate structural evidence. No model call was made during this review.

## Scope

- 40 host calls: 1 text preflight, 4 native-plain UI baselines, 16 strict-simple image rows, 16 strict-medium image rows, and 3 strict-simple UI repeats.
- Four model families and four image fixtures.
- The 12B repeat candidate was not executed; it is not part of the 40-call denominator.

## Transport and structure

- HTTP 200 with no transport error: **40/40**.
- Raw JSON: **36/36 applicable strict-schema calls**. The four native-plain responses are non-JSON by design.
- Independent JSON Schema validation: **36/36 applicable calls**.

These numbers establish transport and structure only. They do not establish semantic correctness.

## Direct manual semantics

| Lane | Visible text exact | Salient text complete | Objects grounded | Salient objects complete | Warnings supported/relevant |
|---|---:|---:|---:|---:|---:|
| Native plain UI | 3/4 | 2/4 | 4/4 | 2/4 | n/a |
| Strict simple image | 10/16 | 13/16 | n/a | n/a | 5/16 |
| Strict medium image | 10/16 | 13/16 | 15/16 | 11/16 | 4/16 |

No row made a forbidden private-data/person claim. Unsupported non-private claims were limited to three rows: one invented cursor occlusion, one erroneous “years January through April” statement, and one hedged “web-based” editor inference.

## Repeatability

All three executed repeat pairs are byte-identical at the raw message level:

- e2b: `sv-03` ↔ `sv-11`
- e4b: `sv-13` ↔ `sv-21`
- 26b: `sv-33` ↔ `sv-41`

This supports exact repeatability only for one strict-simple UI request repeated once on those three models. It does not support broader fixture, schema, or multi-run repeatability. No 12B repeat was executed.

## Validator disagreements

The controller rejected all **35/35** strict image rows. Direct review nevertheless found exact emitted visible text in **22/35** of those rows and grounded object inventories in **15/16** medium rows. Sparse frozen allow-lists and warning-field policy explain many disagreements; genuine OCR errors and unsupported claims remain real row-level failures.

Two prior manual judgments are corrected here: `sv-02` contains the same `применяются`/`применятся` verb error as the e2b strict rows, and `sv-23`'s warning entry describes an informational banner rather than uncertainty.

## Decision boundary

- Transport is confirmed for all 40 calls.
- Raw JSON and schema conformance are confirmed for all 36 applicable strict-schema calls.
- Semantic quality is mixed and must remain row- and dimension-specific.
- Object extraction is demonstrated, but is not uniformly complete or exact.
- Production ranking or recommendation is unsupported by four fixtures and three one-shot repeat pairs.

The owner-only row ledger is bound by SHA-256 `1ffad2666d2208297b5bfe11cc24455a8d4e92d3a0a3629e4184368cf3e6b44e` and is intentionally stored outside the repository.
