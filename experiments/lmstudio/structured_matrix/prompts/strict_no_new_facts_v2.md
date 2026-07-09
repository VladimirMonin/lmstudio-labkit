Return JSON only. Do not use Markdown. Follow the provided JSON schema.

Clean the transcript conservatively:
- restore punctuation and capitalization when the input clearly needs it;
- remove obvious filler words and repeated self-corrections only when they do not carry meaning;
- keep all names, numbers, dates, technical terms, and uncertainty exactly as supported by the input;
- preserve the input language and mixed RU/EN technical style;
- do not summarize, translate, infer decisions, or add context from outside the input.

If cleanup would change meaning, keep the original wording. If no safe cleanup is needed, return the input text unchanged and add a concise warning.

If the schema contains `blocks`, preserve exactly the requested block ids in order. Do not duplicate, omit, or reorder block ids.
