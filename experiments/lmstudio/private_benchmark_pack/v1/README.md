# Private Benchmark Pack v1

## Dataset card

This publication-safe benchmark pack contains 16 deterministically redacted transcript views. It is designed for offline validation of text normalization, structured blocks, ordered stitching, retention probes, and exact-schema behavior. The pack does not contain audio, private source mappings, reviewer identities, private manifests, or model outputs.

### View inventory

The opaque labels are the complete public inventory:

- microphone views: `M01`, `M02`, `M03`, `M04`, `M05`, `M07`, `M08`, `M09`, `M10`, and `M11`;
- processed-recording views: `V10`, `V20`, and `V30`;
- long-recording excerpts: `L02-E`, `L02-M`, and `L02-L`.

Labels identify benchmark views only and cannot be used to recover source identities. Thirteen views are media-unresolved. The three long-recording excerpts have limited media identity evidence, but the public pack includes no audio and establishes no speech-accuracy ground truth.

### Gold and provenance status

All 16 views include structural gold for public unit order, coverage, chunk ownership, reconstruction assertions, placeholder inventory, and public digests. Stored postprocessing is always a reference candidate unless independently admitted as semantic gold.

Two independent source reviews plus private adjudication approved semantic gold for `M01` only. Twelve views remain reference-only. The three long-recording views are unsupported as semantic references because their stored full-record candidates are not scoped to the published excerpts. Structural evidence remains usable for every view; semantic scoring is restricted to `M01`.

### Permitted claims

Results may report:

- exact public-schema validity and raw versus transport-normalized JSON validity;
- deterministic public reconstruction, unit order and coverage, and chunk ownership;
- placeholder preservation, mutation, duplication, invention, and ordering;
- text-relative omission, addition, boundary, and retention behavior when the rubric provides the required basis;
- semantic metrics for `M01` only, against its approved text-source-relative target;
- reference-relative comparisons for explicitly marked reference-only views.

### Non-claims

This pack does not establish WER or CER, audio-grounded omission or hallucination, acoustic robustness, VAD quality, diarization, speaker attribution, timestamp alignment, spoken-entity correctness, physical KV-cache reuse, or general model quality. Reference candidates are not semantic truth. The pack itself contains no benchmark execution and no evidence that any model is suitable for production.

### Four-model usage

The intended comparison covers the repository's four declared local model classes: E2B, E4B, 12B, and 26B. Each model must receive the same frozen public fixture, prompt version, output schema, rubric version, context policy, and stop rules. Runs must be sequential and cold unless a separately declared session experiment says otherwise. Model loading, inference, retries, downloads, network access, and paid calls require a separate live authorization; none were performed while producing this pack.

The frozen `normalization-v1` prompt is stored in `prompts/normalization-v1.txt`. `task_bindings.json` is the executable tier-aware inventory: `M01` binds to approved semantic gold, eleven views bind to available explicit `reference_candidate.json` targets, and `M11` plus the three long views expose only structural, context, and retention capabilities. Structural-only views have no normalization prompt, target, output schema, or normalization acceptance. The validator rejects missing, absent, null, reordered, digest-mismatched, or tier-confused bindings.

### Objective scoring

Each executable normalization view has a closed rubric with immutable `exact-target-v1` semantics. The deterministic scorer consumes the target document named by the inventory, accepts an exact target-preserving output, and fails closed on corruption, omission, addition, placeholder damage, target/view mismatch, unavailable target, or tier confusion. `M01` acceptance is semantic-text-relative. The eleven reference acceptances are explicitly reference-relative and never semantic truth. Structural-only views cannot be passed to the normalization scorer, while their structural/context tasks remain executable.

### Reproducibility and validation

The public tree is self-contained. `pack.json` declares the complete 16-view inventory and a SHA-256 digest over every other public file. Per-view fixtures carry deterministic structure digests. Closed Draft 2020-12 schemas cover every public JSON document type. Offline validators apply the matching full document schema and check reconstruction inventory, contiguous unit and chunk order, complete ownership, half-open semantic ranges, public and prompt digests, placeholder taxonomy and inventory, residual protected literals, provenance classes, expected-output status, rubric completeness, semantic-review agreement, score acceptance consistency, and the public/private boundary.

From the repository root, run:

```bash
uv run pytest -q tests/tools/test_private_benchmark_pack_validation.py tests/tools/test_private_benchmark_pack_privacy.py
python scripts/audit_publication_safety.py
```

The private bijection replay resolves either an explicit `PRIVATE_BENCHMARK_PACK_ROOT` or the local owner-only handoff file at `~/.config/lmstudio-labkit/private-benchmark-pack-root`. The handoff file must be mode `0600`, and the private root must deny all group/other permissions. If neither secure source is available, the replay fails rather than skips. Neither the private path nor a private digest is written to the repository or public reports. Rebuilding public assets requires repeating private preparation and independent reviews; editing a checked-in file and refreshing its digest is not a valid provenance path.
