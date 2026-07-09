# L3.28 Gemma Family Expansion Decision Record

Status: prepared-only decision record. Live phases are not complete yet.

## Questions to close

1. Which Gemma models are load-capable?
2. Which Gemma models are generation-capable?
3. Which Gemma models pass `transcript_cleanup/simple`?
4. Which Gemma models pass `structured_json/simple`?
5. Which Gemma models pass `structured_json/blocks`?
6. Which models degrade by language?
7. Which models degrade by context?
8. Which models support images in the current LM Studio route?
9. Which models are allowed into L3.29 full Gemma matrix?
10. Which remain blocked?

## Current status

- E2B/E4B have accepted L3.27 raw-prose evidence for `transcript_cleanup/simple`; E4B is the quality candidate and E2B is the lightweight fallback.
- 12B is conditionally viable for structured JSON only under hardened schema and/or sanitized retry according to L3.10.
- 26B has historical load-only evidence but no current generation proof in this branch of work.
- Vision/image support is not assumed for any Gemma model until current route capability is proven.

## Prepared L3.28 phase gates

| phase | purpose | status | next action |
|---|---|---|---|
| A | readiness metadata | prepared | read-only metadata check only |
| B | 12B/26B load-only | prepared | run only with explicit approval |
| C | Gemma transcript cleanup canary | prepared | run after B passes |
| D | Gemma structured JSON canary | prepared | run after B and C gating |
| E | context screening example | prepared | do not run until C/D choose accepted combinations |
| F | vision capability | prepared | capability preflight before any image canary |

## Interim L3.29 policy

No model/mode is newly admitted into L3.29 by this prepared-only slice. L3.29 admission requires completed L3.28 live/load evidence and privacy-safe artifacts.
