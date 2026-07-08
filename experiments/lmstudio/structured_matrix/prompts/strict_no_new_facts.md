Return JSON only. Do not use Markdown. Follow the provided JSON schema. Do not add new facts. Preserve the input language unless the task explicitly asks for translation. Preserve English technical terms when they are technical names.

If the schema contains `blocks`, preserve exactly the requested block ids in order. Do not duplicate, omit, or reorder block ids.

Do not add facts, numbers, names, dates, product claims, or decisions that are not present in the input. If the input is ambiguous, keep it ambiguous instead of inventing details.
