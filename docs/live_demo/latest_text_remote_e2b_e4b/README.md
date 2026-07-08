# Latest remote text screening snapshot

This directory is the canonical public-safe export target for the latest L3.16 remote-link text screening snapshot.

Generate it from a completed guarded live run with:

```bash
uv run lmstudio-benchmark export-latest-snapshot \
  --run-dir <run-output-dir> \
  --output-dir docs/live_demo/latest_text_remote_e2b_e4b
```

Safety contract:

- no raw prompt text;
- no raw response text;
- no raw base URL, hostname, or path;
- no source run directory path;
- only safe endpoint classification (`base_url_kind`, `base_url_scheme`), aggregate pass/fail counts, model keys/ids, timing/token summaries, and `execution_target` / `resource_telemetry_mode` labels.

This repository state may contain only the exporter contract before the first explicitly approved true-live remote run.
