# Owner decisions: catalog, identity, telemetry, and schema validation

Date: 2026-07-13

Status: read-only owner-decision research for O2-O5. This report recommends product policy; it does not approve a model/task profile, modify a catalog, authorize implementation, or authorize live local/cloud execution.

Machine-readable companion: `2026-07-13_owner_decisions_catalog_identity_schema_telemetry.json`.

## Executive decision

Approve O2-O5 now as fail-closed product contracts:

| Decision | Recommended disposition | Default |
|---|---|---|
| O2 — catalog governance | `approve_now` | A host-owned, versioned, integrity-protected catalog is the only production approval authority. Promotion requires explicit product review; LabKit evidence never promotes automatically. |
| O3 — exact identity/digest | `approve_now` | Match native key, compat ID, format, verified quantization, and an immutable artifact digest. Any missing/ambiguous fact returns typed unavailable; names, sizes, parameter labels, and runtime visibility are not substitutes. |
| O4 — telemetry privacy | `approve_now` | Keep raw identifiers and raw artifact digests inside the local control plane only. Export categorical/count data and purpose-separated HMAC-SHA-256 pseudonyms; do not export raw request, source, expected-ID, prompt, response, path, or user-content values. |
| O5 — complete schema validation | `approve_now` | Use Draft 2020-12 with a complete validator plus a product schema-admission policy. Reject unknown keywords, undeclared dialects/vocabularies, remote references, and unapproved formats before activation; validate every response locally before business/semantic checks. |

These decisions define behavior when evidence is absent; they do not close the separate live evidence gates for model quality, artifact-path resolution on every installation, provider schema capability, or production rollout.

## Evidence boundary

### Current static contracts

- LM Studio native discovery is represented separately from the OpenAI-compatible model list. LabKit retains native key, format, bits-per-weight, size, quantization, loaded-instance context/parallel shape, and a hashed instance reference; compat discovery retains its exact visible ID.
- `ModelIdentityFacts` has native/compat identity facts but no immutable artifact digest. `identity_verified` therefore cannot establish the proposed production identity by itself.
- `RequestEnvelope.safe_metadata()`, `ResponseContract.safe_metadata()`, and metrics currently retain raw `request_id`, `cell_id`, `expected_ids`, `model_id`, and unkeyed content-derived SHA-256 values in some safe/public projections. They exclude raw prompt/response text, but those stable identifiers/digests remain correlatable and are too permissive for product telemetry reuse.
- LabKit has two deliberate schema subsets: `tools/lmstudio_lab/structured.py` explicitly labels its check as minimal shape validation, and `lmstudio_labkit/validation.py` recognizes only selected keywords. Unknown types currently fall through as a match, unknown keywords are ignored, `items: false` is not enforced by its recursive subset, and no meta-schema/dialect validation occurs.
- The package does not currently depend on a complete JSON Schema implementation.

Relevant local evidence:

- `libs/lmstudio_managed/registry/identity.py`
- `libs/lmstudio_managed/registry/api_models.py`
- `tools/lmstudio_lab/identity_probe.py`
- `lmstudio_labkit/requests.py`
- `tools/lmstudio_lab/privacy.py`
- `tools/lmstudio_lab/metrics.py`
- `lmstudio_labkit/validation.py`
- `lmstudio_labkit/schema_builders.py`
- `tools/lmstudio_lab/structured.py`
- `tests/lmstudio_labkit/test_schema_keywords.py`

### Retained executed evidence

The architecture retains exact-token, structured-context, and structured-vision observations, but none establishes a production catalog or universal artifact digest. The bounded vision closure showed that 36/36 applicable calls could pass raw parse and independent schema validation while semantic dimensions remained mixed. Therefore catalog admission requires task-specific evidence, and schema validity remains only one acceptance layer.

### Official external facts

1. LM Studio documents `GET /api/v1/models` as returning a model `key`, quantization name/bits, `size_bytes`, `format`, capabilities, and loaded instances with instance `id` and runtime config. It does not document an immutable model-artifact digest in that response. Source: https://lmstudio.ai/docs/developer/rest/list
2. LM Studio documents `GET /v1/models` as the OpenAI-compatible list of models visible to the server; with Just-In-Time loading it may include all downloaded models. Visibility is therefore not approval and does not prove loaded runtime identity. Source: https://lmstudio.ai/docs/developer/openai-compat/models
3. JSON Schema Draft 2020-12 says unknown keywords should be treated as annotations. A product that needs fail-closed schemas must add its own schema-admission rule rather than assuming a standards-compliant validator rejects unknown keywords. Source: https://json-schema.org/draft/2020-12/json-schema-core.html
4. Draft 2020-12 defines validation/applicator behavior including required fields, string/array bounds, and object applicators. Source: https://json-schema.org/draft/2020-12/json-schema-validation.html
5. `python-jsonschema` documents that validator instances assume the schema is valid and recommends `Validator.check_schema`; it also states that `format` is not asserted unless a format checker is supplied. Source: https://python-jsonschema.readthedocs.io/en/stable/validate/
6. RFC 2104 defines HMAC as message authentication using a cryptographic hash with a shared secret key. Source: https://www.rfc-editor.org/rfc/rfc2104
7. RFC 8785 defines deterministic JSON canonicalization for repeatable hashing and signing. Source: https://www.rfc-editor.org/rfc/rfc8785
8. The Update Framework specification describes signed/versioned metadata and protections against rollback, freeze, and mix-and-match attacks. The proposed catalog borrows these updater properties; it does not require a full TUF deployment for an initially local-only catalog. Source: https://theupdateframework.github.io/specification/latest/

External documentation was retrieved on 2026-07-13 UTC.

## O2 — product-owned approved catalog

### Approval unit

The smallest approval unit is `ApprovedTaskProfile`, not a model family or artifact alone. A profile binds:

- `profile_id` and `profile_version`;
- task and response-contract versions;
- required endpoint family and capabilities;
- exact artifact identity policy;
- approved context tier, runtime parallelism, and application concurrency;
- output, timeout, and cumulative call policy;
- validator, semantic-policy, fallback, and persistence-policy versions;
- platform/runtime constraints and memory-envelope evidence;
- evidence references and approval state;
- `auto_eligible` independently from `approved`.

One artifact may be approved for one task/shape and unavailable for another.

### Catalog envelope v1

The signed/integrity-protected payload should contain:

```text
catalog_schema_version
catalog_id
revision                 monotonic unsigned integer
issued_at / expires_at
minimum_host_version
previous_payload_digest  null only for genesis
profiles[]
revocations[]
keyset_version
```

The outer envelope contains `payload_digest`, signatures with `key_id`/algorithm, and canonicalization identifier. Use JCS (RFC 8785) bytes for hashing/signing. The local product trust store, not the catalog payload, owns trusted root keys.

Recommended initial signature policy: one offline product-release signing key, Ed25519, with an explicit key-rotation record. If signing infrastructure is not available in the first offline implementation, allow only an embedded catalog shipped inside the authenticated application package and classify external catalog updates as `catalog_update_unsupported`; do not replace signatures with a plain checksum.

### Promotion workflow

1. **Propose:** create a candidate profile with exact identity and task/shape evidence references. Candidate is non-runnable.
2. **Static validation:** validate catalog schema, canonicalization, signature, revision chain, unique IDs, closed enums, digest syntax, and cross-references.
3. **Evidence review:** an independent reviewer verifies that evidence is task-, artifact-, runtime-, context-, parallelism-, concurrency-, and validator-specific. Lab status/ranking is advisory only.
4. **Owner approval:** the product owner explicitly changes the profile from `candidate` to `approved`; `auto_eligible` requires a separate affirmative decision.
5. **Stage:** write the new catalog to a temporary immutable location and run offline reconciliation against synthetic/discovered inventory without selecting or loading a model.
6. **Activate atomically:** advance one current-catalog pointer only after every gate passes; retain the previous accepted revision.
7. **Observe:** telemetry can report only the catalog revision pseudonym and categorical outcomes. No telemetry event can mutate catalog state.

No benchmark runner, LabKit registry, runtime discovery result, updater, or telemetry service has promotion authority.

### Updater and rollback

Updater behavior:

- fetch/stage is separate from activate;
- require signature, trusted key, canonical payload digest, non-expired metadata, compatible host version, and a strictly increasing revision;
- require `previous_payload_digest` to equal the current accepted payload digest;
- reject mixed profile fragments; activate one complete snapshot;
- keep the current and at least one previous accepted payload plus activation journal;
- activation is an atomic pointer swap with read-back.

Rollback behavior:

- a global kill switch disables new Auto selection immediately and increments catalog generation so in-flight recommendations cannot commit;
- ordinary recovery reactivates the previous known-good payload through a new signed rollback authorization that names the target digest and creates a new higher revision; simply replaying an old lower revision is rejected;
- already persisted accepted results remain readable by catalog/profile/validator version;
- rollback never approves an otherwise unapproved artifact and never unloads externally owned runtime instances.

### Typed catalog outcomes

At minimum:

- `catalog_missing`
- `catalog_schema_invalid`
- `catalog_signature_invalid`
- `catalog_key_untrusted`
- `catalog_expired`
- `catalog_revision_rollback_rejected`
- `catalog_chain_mismatch`
- `catalog_host_incompatible`
- `catalog_profile_revoked`
- `catalog_profile_not_approved`
- `catalog_profile_manual_only`
- `catalog_update_unsupported`

Every state prevents Auto selection. Manual selection remains limited to exact, approved, non-revoked profiles and cannot bypass hard identity/capability/memory failures.

## O3 — exact identity and digest policy

### Separate three identity scopes

1. **Catalog artifact identity:** immutable approval identity.
2. **Runtime identity:** the exact native key, compat ID, loaded instance, and effective runtime shape observed now.
3. **Telemetry identity:** a pseudonymous correlation value; never the approval authority.

Do not reuse one digest for all three scopes.

### Required exact binding

A production match requires:

```text
native_model_key
compat_model_id
format
quantization_name
quantization_verified = true
artifact_digest_algorithm = sha256
artifact_digest
artifact_digest_source
artifact_digest_scope
```

`artifact_digest_source` is one of:

- `computed_artifact_bytes`: SHA-256 computed over the safely resolved immutable model artifact;
- `trusted_signed_manifest`: SHA-256 supplied by a signature-verified artifact manifest whose subject and byte scope are explicit.

`artifact_digest_scope` must identify exactly what was hashed, for example `single_file_bytes` or `signed_manifest_subject`. Multi-file formats require a signed manifest or a versioned deterministic bundle-manifest digest; concatenating directory files ad hoc is forbidden.

Native key, compat ID, format, and quantization are reconciliation facts, not substitutes for the artifact digest. Loaded-instance ID is runtime state, not durable artifact identity. Size and bits-per-weight are consistency checks only.

### Artifact resolver boundary

The resolver may inspect a local path in-process only after validating that it belongs to an LM Studio inventory record and resolves to a regular, non-symlinked immutable artifact under an approved model root. It streams the file into SHA-256, does not publish or log the path, and returns only digest/scope/status to the control plane. TOCTOU protection should bind stable file metadata before/after hashing or use a runtime/trusted manifest handle.

If those conditions cannot be proven, do not search arbitrary user directories and do not infer a digest from a model ID.

### Typed identity outcomes

- `identity_exact`
- `native_identity_missing`
- `compat_identity_missing`
- `identity_ambiguous`
- `identity_mismatch`
- `format_missing`
- `format_mismatch`
- `quantization_unknown`
- `quantization_mismatch`
- `artifact_missing`
- `artifact_digest_unavailable`
- `artifact_digest_source_untrusted`
- `artifact_digest_scope_unsupported`
- `artifact_digest_mismatch`
- `runtime_shape_mismatch`

Only `identity_exact` may reach Auto ranking. Digest unavailable is a normal typed unavailable state, not an implementation exception and not a reason to lower confidence.

## O4 — privacy-safe telemetry and digest governance

### Data classification

| Class | Local control plane | Exported telemetry |
|---|---|---|
| Raw native/compat IDs, loaded-instance ID | Ephemeral/current reconciliation; raw catalog value permitted in protected local policy | Never by default |
| Raw artifact SHA-256 | Protected local catalog and resolver result | Never by default |
| Request/cell/job/source/expected IDs | In-memory and product persistence where operationally required | Never |
| Prompt/source/response/image bytes and local paths | In-memory/product source storage only | Never |
| Public schema/catalog/profile version | Permitted if it is product-public and contains no user-derived value | Permitted |
| Counts, timings, token usage, categorical verdicts/reason codes | Permitted | Permitted after bounds/cardinality review |
| Correlation identifiers | Local raw IDs may exist | Purpose-separated keyed pseudonyms only |

### Pseudonym contract v1

Use HMAC-SHA-256 with a secret telemetry key held outside logs/artifacts:

```text
pseudonym = base64url(
  HMAC-SHA-256(key_epoch,
    "lmstudio-labkit-telemetry-v1\0" + purpose + "\0" + canonical_value
  )
)
```

Requirements:

- separate `purpose` values for artifact, model route, request, source, schema-private, and expected-ID-set correlation;
- canonicalize structured values with JCS before HMAC;
- include a non-secret `key_epoch` label, rotate keys by retention window, and do not retain old keys beyond approved correlation needs;
- truncate only after a collision analysis for the event volume; default to the full 256-bit output;
- never expose the key or raw-to-pseudonym lookup table;
- do not use unkeyed hashes for low-entropy/user-derived identifiers;
- a public immutable schema or public catalog payload may use unkeyed SHA-256 for integrity, but that integrity digest must not be reused as a private event pseudonym.

If the telemetry key is unavailable, emit `telemetry_identity_omitted` and keep categorical/count telemetry; do not fall back to unkeyed hashing.

### Minimum event shape

```text
event_schema_version
occurred_at_bucket
catalog_revision_ref
profile_ref
artifact_ref
request_ref
schema_or_contract_version
endpoint_family
attempt_index
outcome_category / reason_codes
latency and token counts
expected_count / observed_count
duplicate/missing/extra/reordered counts
parse/schema/business/semantic/fallback/persistence categorical verdicts
telemetry_key_epoch
```

Use bounded enums and numeric limits. Do not include raw validator messages that may embed instance values or paths; map them to stable keyword/category and bounded instance-path shape.

### Retention and access defaults

- product diagnostics: short configurable retention, default 30 days;
- aggregate counters: may outlive event rows when no pseudonyms remain;
- raw prompts/responses/images: zero telemetry retention;
- separate security/admin access to the local catalog from analytics access;
- deletion of a source/request must not require recovering raw content from telemetry.

These are configurable starting defaults, not a legal retention determination.

## O5 — complete JSON Schema strategy

### Decision

Adopt JSON Schema Draft 2020-12 for product response contracts. Use a complete implementation in the dependency-light core; for Python the practical default is `jsonschema` with `Draft202012Validator` (or `validator_for` after dialect admission), `check_schema`, a preloaded local registry, and deterministic error projection.

The standards-compliant validator and the product admission policy have different jobs:

1. **Schema admission** rejects schemas outside the product profile.
2. **Meta-schema validation** proves the admitted schema is valid for the declared dialect.
3. **Instance validation** validates untouched parsed JSON.
4. **Business/semantic validation** enforces exact IDs/order, ownership, protected values, task semantics, and product behavior.

API-bound `strict: true` is not evidence that steps 2-4 ran locally.

### Product schema profile v1

Required:

- exact `$schema`: `https://json-schema.org/draft/2020-12/schema` in stored canonical contracts;
- root and nested object closure with `additionalProperties: false` where the contract is closed;
- explicit `type`, `required`, and item/property schemas;
- only product-approved keywords;
- canonical schema digest and validator/profile versions.

Initial allowed assertion/applicator subset:

- `$schema`, `$id` (product-local URN only), `$defs`, `$ref` (local fragment or preloaded product registry only);
- `type`, `const`, `enum`;
- `properties`, `required`, `additionalProperties`;
- `items`, `prefixItems`, `minItems`, `maxItems`, `uniqueItems`;
- `minLength`, `maxLength`, `pattern`;
- `minimum`, `maximum`;
- `allOf`, `anyOf`, `oneOf`, `not` only after dedicated adversarial tests exist.

Rejected at admission unless a later profile version explicitly adds them:

- unknown/custom keywords and undeclared vocabularies;
- remote HTTP(S) `$ref` or dynamic network resolution;
- `format`, `contentEncoding`, `contentMediaType`, and `contentSchema` in acceptance-critical positions;
- defaults/coercion/repair extensions;
- implementation-specific keywords;
- schemas without a declared dialect.

Because Draft 2020-12 treats unknown keywords as annotations, unknown-keyword rejection is an explicit recursive admission-linter rule over every schema location. Boolean schemas are valid schemas and must be handled deliberately; the current subset's treatment of `items: false` is not sufficient.

### Validation execution

For each activated contract:

1. Canonicalize the schema with JCS and verify its catalog/manifest digest.
2. Run the admission linter recursively.
3. Resolve only local/preloaded references and reject registry misses.
4. Run `Draft202012Validator.check_schema(schema)`.
5. Construct/cache a validator keyed by schema digest + validator version + profile version.
6. Parse untouched raw JSON with no repair/coercion/defaulting.
7. Collect all instance errors deterministically, sort by JSON instance path + schema path + validator keyword, and emit only safe categories/counts.
8. Require zero schema errors.
9. Continue to exact business identity/order, semantic, cancellation-generation, persistence, and read-back gates.

A validator unavailable/import failure, schema admission failure, registry miss, or unknown keyword returns typed unavailable and prevents provider submission for that contract.

### Typed schema outcomes

- `schema_contract_ready`
- `schema_dialect_missing`
- `schema_dialect_unsupported`
- `schema_unknown_keyword`
- `schema_vocabulary_unsupported`
- `schema_remote_reference_forbidden`
- `schema_reference_unresolved`
- `schema_meta_invalid`
- `schema_digest_mismatch`
- `validator_unavailable`
- `validator_version_unreadable`
- `instance_raw_json_invalid`
- `instance_schema_invalid`

None of these outcomes may be normalized into success.

### Rollback seam

Every task profile pins `response_contract_id`, schema digest, schema-profile version, and validator version. A task-level kill switch prevents new submissions and advances request generation. Rollback activates a previously accepted catalog revision through the signed higher-revision rollback procedure. Historical accepted records remain readable with their pinned versions; if an old validator cannot be loaded safely, the record is readable as historical data but cannot be revalidated or promoted.

## Minimum acceptance tests

### Catalog/updater

1. Valid signed genesis and next revision stage and activate atomically.
2. Tampered payload, signature, untrusted key, expired metadata, wrong previous digest, duplicate profile ID, and host-version mismatch all fail closed.
3. Lower revision replay and mix-and-match profile fragments are rejected.
4. Lab candidate/benchmark changes never mutate the active catalog.
5. Activation crash before/after pointer swap recovers deterministically.
6. Kill switch invalidates in-flight recommendation generation.
7. Signed higher-revision rollback reactivates exactly the previous known-good digest; plain old-revision replay fails.

### Identity

1. Exact native+compat+format+quantization+artifact digest passes.
2. Each missing field returns its typed unavailable state.
3. Same name/size with a different digest fails.
4. Same digest with incompatible format/quantization/runtime shape fails.
5. Ambiguous compat/native mappings fail rather than pick first.
6. Resolver never logs/persists path, rejects symlink/out-of-root/changed-during-hash input, and does not scan arbitrary directories.
7. Multi-file artifact without a trusted deterministic manifest returns unsupported scope.

### Telemetry

1. Raw prompt/response/source/image/path/native ID/compat ID/artifact digest/request ID/expected IDs never appear in serialized events or error text.
2. Same value+purpose+epoch yields the same pseudonym; another purpose or epoch differs.
3. Missing key omits pseudonyms without unkeyed fallback.
4. Validator errors expose bounded category/path shape only, never rejected values.
5. Cardinality/length bounds reject oversized free-form fields.
6. Retention removes event pseudonyms while preserving approved aggregates.

### Schema validation

1. Every admitted schema declares Draft 2020-12 and passes `check_schema`.
2. Unknown keyword at root or nested schema, remote `$ref`, undeclared vocabulary, unsupported format, and digest mismatch fail before transport.
3. Required/additional-property/type/enum/const/string/array/numeric boundaries are covered with valid and invalid fixtures.
4. Boolean schemas, `items: false`, `prefixItems`, nested `$defs`/local `$ref`, and unresolved refs have explicit tests.
5. Duplicate, missing, extra, reordered, wrong-type, empty block results can pass/fail schema independently but always fail the subsequent exact business gate when defective.
6. Provider-claimed strict output is locally revalidated; repaired, fenced, coerced, or defaulted JSON never counts as raw/schema success.
7. Validator dependency missing or version unreadable returns typed unavailable.
8. Error ordering/projection is deterministic and privacy safe.
9. Schema success cannot bypass semantic, cancellation-generation, persistence, or read-back gates.

## Approval and non-claims

Approve these policy records as Stage-0 defaults. Implementation should remain offline until separate cards are approved. Production promotion remains blocked by exact artifact resolver support on the target installation, task-specific semantic evidence, provider/runtime capability evidence, persistence/control-plane gates, and separately authorized shadow/canary execution.

This report does not:

- approve any model, task profile, catalog entry, digest source, or rollout percentage;
- claim that LM Studio's model APIs expose an artifact digest;
- claim the current LabKit schema subset is complete;
- claim HMAC pseudonyms make event data anonymous;
- authorize model discovery, hashing, loading, inference, cloud calls, migration, implementation, commit, or push.
