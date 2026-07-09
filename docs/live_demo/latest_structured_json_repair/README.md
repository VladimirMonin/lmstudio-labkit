# Latest Structured JSON Repair Snapshot

This directory contains the sanitized L3.28d.1 structured JSON repair snapshot.

Raw prompt/response artifacts are not stored here and were not required for this repair slice.

## Result

- E2B/E4B repair canary: 8/8 pass.
- 12B repair rerun: 8/8 pass.
- Combined: 16/16 pass.
- JSON parse/schema/language/id-exact pass rates: 1.0 for all included models.
- 26B structured JSON generation: not run; still blocked.

## Admission

The repaired canary admits E2B, E4B, and 12B for bounded structured JSON simple/blocks screening.
26B remains structured-blocked until a separate approved tiny structured canary.
